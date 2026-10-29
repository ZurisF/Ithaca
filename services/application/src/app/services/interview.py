"""Gate 3 stage entry: validate PG facts, call dependencies, conditionally publish."""

import json
import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.bank.retrieval import QuestionCandidate, QuestionRetriever
from app.domain.access import Identity
from app.domain.contracts import (
    InterviewPlan,
    InterviewView,
    SectionRef,
    SessionView,
    SupervisorDecision,
    TurnView,
)
from app.domain.rules import exact_question_id, parse_sections, validate_plan
from app.repositories import interview as repo
from app.repositories import prepare as prepare_repo
from app.services.errors import AppError
from app.services.interview_checkpoint import (
    execution_lock,
    notify_current_changed,
    read_checkpoint,
    write_checkpoint,
)
from app.services.planning import _validate_versions
from app.services.session_access import owned_session, require_preparing
from app.settings import get_settings
from model_adapter import Message, ModelAdapter, ModelFailure, RetryPolicy

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[5]
ASSETS = ROOT / "packages/planning_assets"
PROMPT = ROOT / "packages/prompt_assets/prompts/supervisor/v1.md"


async def get_current_view(db: AsyncSession, identity: Identity, session_id: UUID) -> InterviewView:
    async with db.begin():
        row = await owned_session(db, session_id, identity, lock=False)
        stored_plan = await prepare_repo.get_plan(db, session_id)
        plan = InterviewPlan.model_validate(stored_plan) if stored_plan else None
        stage_index = (
            await repo.first_open_stage(db, session_id, len(plan.stages)) if plan else None
        )
        latest = await repo.latest_turn(db, session_id)
    try:
        checkpoint = await read_checkpoint(session_id) if row["status"] == "interviewing" else None
    except Exception:  # noqa: BLE001 - PG remains the published business view
        checkpoint = None
        logger.warning("interview_checkpoint_read_failed")
    awaiting = None
    if row["status"] == "interviewing":
        if latest is not None and latest["answer"] is None:
            awaiting = "answer"
        elif checkpoint is not None and checkpoint.get("awaiting") in {
            "answer",
            "snapshot_confirmation",
            "decision_retry",
        }:
            awaiting = checkpoint["awaiting"]
    return InterviewView(
        session=SessionView.model_validate(dict(row)),
        plan=plan,
        current_stage_index=stage_index,
        current_turn=TurnView.model_validate(dict(latest)) if latest else None,
        awaiting=awaiting,
        pending_correction=None,
        last_error_code=(checkpoint or {}).get("last_error_code")
        if awaiting == "decision_retry"
        else None,
    )


def _validate_start_facts(row, snapshot: str | None, plan: InterviewPlan | None) -> None:
    if snapshot is None or row["interview_direction"] is None or plan is None:
        raise AppError(409, "state_conflict", "请先完成项目快照、范围和面试计划。")
    available = parse_sections(snapshot)
    selected = [SectionRef.model_validate(item) for item in row["selected_sections"]]
    if (available and not selected) or any(item not in available for item in selected):
        raise AppError(409, "state_conflict", "所选范围与当前快照不一致。")
    manifest = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
    topics = json.loads((ASSETS / "topics.yaml").read_text(encoding="utf-8"))
    policy = json.loads(
        (ASSETS / "policies" / f"{manifest['planning_policy']}.yaml").read_text(encoding="utf-8")
    )
    errors = [
        *validate_plan(
            plan, selected, {item["path"] for item in topics["topics"]}, policy["max_stages"]
        ),
        *_validate_versions(plan, row["interview_direction"], manifest),
    ]
    if errors:
        raise AppError(409, "plan_invalid", "当前面试计划已失效，请重新生成。")


async def _publish_first_question(
    db: AsyncSession,
    identity: Identity,
    session_id: UUID,
    snapshot: str,
    plan: InterviewPlan,
    candidates: list[QuestionCandidate],
    decision: SupervisorDecision,
) -> bool:
    async with db.begin():
        row = await owned_session(db, session_id, identity, lock=True)
        if row["status"] != "interviewing":
            return False
        if await prepare_repo.get_snapshot(db, session_id) != snapshot:
            return False
        if await prepare_repo.get_plan(db, session_id) != plan.model_dump():
            return False
        if await repo.first_open_stage(db, session_id, len(plan.stages)) != 0:
            return False
        if await repo.latest_turn(db, session_id) is not None:
            return False
        question_id = exact_question_id(
            decision.question or "",
            ((item.question_id, item.question) for item in candidates),
        )
        return await repo.publish_first_turn(db, session_id, decision.question or "", question_id)


async def _run_first_question(
    db: AsyncSession,
    identity: Identity,
    session_id: UUID,
    row,
    snapshot: str,
    plan: InterviewPlan,
    model: ModelAdapter,
    retriever: QuestionRetriever,
) -> InterviewView:
    stage = plan.stages[0]
    settings = get_settings()
    try:
        candidates = await retriever.retrieve_for_turn(
            session_id, stage.goal, stage.topic_path, settings.retrieval_limit
        )
    except Exception:  # noqa: BLE001 - controlled retrieval adapters also degrade to empty
        logger.warning("retrieval_failed_at_stage_entry")
        candidates = []
    prompt = PROMPT.read_text(encoding="utf-8")
    payload = {
        "snapshot": snapshot,
        "interview_direction": row["interview_direction"],
        "selected_sections": row["selected_sections"],
        "plan": plan.model_dump(mode="json"),
        "current_stage_index": 0,
        "retrieved_questions": [candidate.question for candidate in candidates],
        "trigger": "stage_entry",
    }

    def validate(candidate: SupervisorDecision) -> list[str]:
        try:
            candidate.validate_stage_entry()
        except ValueError:
            return ["stage entry requires continue, no user acts and no interviewer message"]
        return []

    try:
        decision = await model.generate_structured(
            session_id=session_id,
            operation="supervisor_stage_entry",
            messages=[
                Message(role="system", content=prompt),
                Message(role="user", content=json.dumps(payload, ensure_ascii=False)),
            ],
            output_schema=SupervisorDecision,
            prompt_version="v1",
            retry_policy=RetryPolicy(
                max_attempts=settings.model_max_attempts,
                deadline_seconds=settings.model_timeout_seconds,
            ),
            validate_output=validate,
        )
        if validate(decision):
            raise ModelFailure("output_invalid")
    except ModelFailure as exc:
        try:
            await write_checkpoint(session_id, awaiting="decision_retry", error=exc.code)
        except Exception as checkpoint_exc:
            raise AppError(
                503, "dependency_unavailable", "面试进度暂时无法保存。", True
            ) from checkpoint_exc
        return await get_current_view(db, identity, session_id)

    published = await _publish_first_question(
        db, identity, session_id, snapshot, plan, candidates, decision
    )
    if published:
        try:
            await write_checkpoint(session_id, awaiting="answer")
        except Exception:  # noqa: BLE001 - PG turn is already authoritative
            logger.warning("interview_checkpoint_write_failed_after_publish")
        try:
            await notify_current_changed(session_id)
        except Exception:  # noqa: BLE001 - SSE is disposable
            logger.warning("interview_notification_failed")
    return await get_current_view(db, identity, session_id)


async def start(
    db: AsyncSession,
    identity: Identity,
    session_id: UUID,
    model: ModelAdapter,
    retriever: QuestionRetriever,
) -> InterviewView:
    async with db.begin():
        await owned_session(db, session_id, identity, lock=False)
    async with execution_lock(session_id):
        async with db.begin():
            row = await owned_session(db, session_id, identity, lock=True)
            if row["status"] == "interviewing":
                already_started = True
                snapshot = None
                plan = None
            else:
                require_preparing(row)
                stored = await prepare_repo.get_plan(db, session_id)
                plan = InterviewPlan.model_validate(stored) if stored is not None else None
                snapshot = await prepare_repo.get_snapshot(db, session_id)
                _validate_start_facts(row, snapshot, plan)
                await repo.enter_interview(db, session_id)
                already_started = False
        if already_started:
            return await get_current_view(db, identity, session_id)
        assert snapshot is not None and plan is not None
        return await _run_first_question(
            db, identity, session_id, row, snapshot, plan, model, retriever
        )


async def retry_first_question(
    db: AsyncSession,
    identity: Identity,
    session_id: UUID,
    model: ModelAdapter,
    retriever: QuestionRetriever,
) -> InterviewView:
    async with db.begin():
        await owned_session(db, session_id, identity, lock=False)
    async with execution_lock(session_id):
        checkpoint = await read_checkpoint(session_id)
        if checkpoint is None or checkpoint.get("awaiting") != "decision_retry":
            raise AppError(409, "retry_not_available", "当前没有可重试的面试决策。")
        async with db.begin():
            row = await owned_session(db, session_id, identity, lock=True)
            if row["status"] != "interviewing" or await repo.latest_turn(db, session_id):
                raise AppError(409, "retry_not_available", "当前没有可重试的首题决策。")
            stored = await prepare_repo.get_plan(db, session_id)
            plan = InterviewPlan.model_validate(stored) if stored is not None else None
            snapshot = await prepare_repo.get_snapshot(db, session_id)
            if (
                snapshot is None
                or plan is None
                or await repo.first_open_stage(db, session_id, len(plan.stages)) != 0
            ):
                raise AppError(409, "retry_not_available", "当前没有可重试的首题决策。")
        return await _run_first_question(
            db, identity, session_id, row, snapshot, plan, model, retriever
        )
