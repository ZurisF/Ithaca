"""Planner command: read facts, call model outside a transaction, conditionally publish."""

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access import Identity
from app.domain.contracts import InterviewPlan, SectionRef
from app.domain.rules import parse_sections, validate_plan
from app.repositories import prepare as repo
from app.services.errors import AppError
from app.services.session_access import owned_session, require_preparing
from app.settings import get_settings
from model_adapter import Message, ModelAdapter, ModelFailure, RetryPolicy

ROOT = Path(__file__).resolve().parents[5]
ASSETS = ROOT / "packages/planning_assets"
PROMPT = ROOT / "packages/prompt_assets/prompts/planner/v1.md"


def _asset(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class PlanningAssets:
    manifest: dict
    topics: dict
    policy: dict


def load_planning_assets() -> PlanningAssets:
    manifest = _asset(ASSETS / "manifest.json")
    return PlanningAssets(
        manifest=manifest,
        topics=_asset(ASSETS / "topics.yaml"),
        policy=_asset(ASSETS / "policies" / f"{manifest['planning_policy']}.yaml"),
    )


def validate_plan_against_assets(
    plan: InterviewPlan,
    direction: str,
    selected: list[SectionRef],
    assets: PlanningAssets,
) -> list[str]:
    manifest = assets.manifest
    errors = validate_plan(
        plan,
        selected,
        {item["path"] for item in assets.topics["topics"]},
        assets.policy["max_stages"],
    )
    if plan.template_id != direction or plan.template_version != manifest["templates"][direction]:
        errors.append("template identity or version does not match")
    if plan.topic_registry_version != manifest["topic_registry"]:
        errors.append("topic registry version does not match")
    if plan.planning_policy_version != manifest["planning_policy"]:
        errors.append("planning policy version does not match")
    return errors


async def get_plan(db: AsyncSession, identity: Identity, session_id: UUID) -> InterviewPlan:
    await owned_session(db, session_id, identity, lock=False)
    stored = await repo.get_plan(db, session_id)
    if stored is None:
        raise AppError(404, "plan_not_found", "当前会话还没有面试计划。")
    return InterviewPlan.model_validate(stored)


async def generate_plan(
    db: AsyncSession, identity: Identity, session_id: UUID, model: ModelAdapter
) -> InterviewPlan:
    assets = load_planning_assets()
    manifest = assets.manifest
    topics = assets.topics
    policy = assets.policy
    prompt = PROMPT.read_text(encoding="utf-8")

    async with db.begin():
        row = await owned_session(db, session_id, identity, lock=False)
        require_preparing(row)
        existing = await repo.get_plan(db, session_id)
        if existing is not None:
            return InterviewPlan.model_validate(existing)
        snapshot = await repo.get_snapshot(db, session_id)
        if snapshot is None or row["interview_direction"] is None:
            raise AppError(409, "state_conflict", "请先完成快照和面试范围选择。")
        direction = row["interview_direction"]
        selected = [SectionRef.model_validate(item) for item in row["selected_sections"]]
        available = parse_sections(snapshot)
        if (available and not selected) or any(item not in available for item in selected):
            raise AppError(409, "state_conflict", "所选范围与当前快照不一致。")
        template = _asset(
            ASSETS / "templates" / direction / f"{manifest['templates'][direction]}.yaml"
        )

    def validate(candidate: InterviewPlan) -> list[str]:
        return validate_plan_against_assets(candidate, direction, selected, assets)

    payload = {
        "snapshot": snapshot,
        "direction": direction,
        "selected_sections": [item.model_dump() for item in selected],
        "topics": topics,
        "template": template,
        "policy": policy,
        "required_versions": {
            "template_id": direction,
            "template_version": manifest["templates"][direction],
            "topic_registry_version": manifest["topic_registry"],
            "planning_policy_version": manifest["planning_policy"],
        },
    }
    settings = get_settings()
    try:
        plan = await model.generate_structured(
            session_id=session_id,
            operation="planner",
            messages=[
                Message(role="system", content=prompt),
                Message(role="user", content=json.dumps(payload, ensure_ascii=False)),
            ],
            output_schema=InterviewPlan,
            prompt_version=manifest["prompts"]["planner"],
            retry_policy=RetryPolicy(
                max_attempts=settings.model_max_attempts,
                deadline_seconds=settings.model_timeout_seconds,
            ),
            validate_output=validate,
        )
    except ModelFailure as exc:
        if exc.code == "dependency_unavailable":
            raise AppError(503, "dependency_unavailable", "模型尚未配置。") from exc
        if exc.code in {"output_invalid", "schema_invalid"}:
            raise AppError(422, "plan_invalid", "模型未生成有效的面试计划。") from exc
        raise AppError(503, "model_call_failed", "计划生成暂时失败，请稍后重试。", True) from exc

    # Controlled test adapters must obey the same deterministic barrier as production.
    if validate(plan):
        raise AppError(422, "plan_invalid", "模型未生成有效的面试计划。")
    async with db.begin():
        current = await owned_session(db, session_id, identity, lock=True)
        require_preparing(current)
        existing = await repo.get_plan(db, session_id)
        if existing is not None:
            return InterviewPlan.model_validate(existing)
        if (
            await repo.get_snapshot(db, session_id) != snapshot
            or current["interview_direction"] != direction
            or current["selected_sections"] != [item.model_dump() for item in selected]
        ):
            raise AppError(409, "state_conflict", "项目材料或选择已变化，请重新生成计划。")
        await repo.save_plan(db, session_id, plan.model_dump_json())
    return plan
