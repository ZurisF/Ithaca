"""Terminal commands, finalization graph and PostgreSQL-backed result projection."""

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import TypedDict
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
from langgraph.graph import END, START, StateGraph
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import session_factory
from app.domain.access import Identity
from app.domain.contracts import (
    FeedbackView,
    IdealAnswer,
    InterviewPlan,
    ProjectAnswerItem,
    ProjectAnswers,
    Report,
    ResultTurn,
    ResultView,
    SessionView,
    StrictModel,
    TurnEvaluation,
)
from app.repositories import finalization as repo
from app.repositories import interview as interview_repo
from app.repositories import prepare as prepare_repo
from app.services.errors import AppError
from app.services.interview_checkpoint import delete_checkpoint, notify_current_changed
from app.services.session_access import owned_session
from app.settings import get_settings
from content_safety import ContentRejected, filter_text
from model_adapter import Message, ModelAdapter, ModelFailure, RetryPolicy

logger = logging.getLogger(__name__)
PROMPTS = Path(__file__).resolve().parents[5] / "packages/prompt_assets/prompts/post"


def _safe(value: str, limit: int) -> str:
    try:
        return filter_text(value, max_chars=limit).text
    except ContentRejected as exc:
        raise AppError(422, "safety_filter_rejected", "赛后内容未通过安全检查。") from exc


async def _changed(session_id: UUID) -> None:
    try:
        await notify_current_changed(session_id)
    except Exception:  # noqa: BLE001
        logger.warning("finalization_notification_failed")


async def _clear_checkpoint(session_id: UUID) -> None:
    try:
        await delete_checkpoint(session_id)
    except Exception:  # noqa: BLE001 - PG terminal status remains authoritative
        logger.warning("terminal_checkpoint_delete_failed")


async def terminate(
    db: AsyncSession, identity: Identity, session_id: UUID, reason: str
) -> SessionView:
    """A single row lock decides all external terminal commands."""
    if reason not in {"early_finish", "forced_exit"}:
        raise ValueError("invalid external termination reason")
    changed = False
    async with db.begin():
        row = await owned_session(db, session_id, identity, lock=True)
        if reason == "early_finish" and row["status"] == "interviewing":
            await terminate_locked(db, session_id, reason)
            changed = True
        elif reason == "forced_exit" and row["status"] in {"interviewing", "post_processing"}:
            if row["status"] == "post_processing":
                if await repo.has_published_artifacts(db, session_id):
                    return SessionView.model_validate(dict(row))
                await repo.cancel_tasks(db, session_id)
            await db.execute(
                text("""
                UPDATE app.interview_sessions SET status = 'aborted',
                    termination_reason = 'forced_exit',
                    feedback_frozen_at = COALESCE(feedback_frozen_at, now()),
                    completed_at = now(), updated_at = now()
                WHERE id = :id
            """),
                {"id": session_id},
            )
            changed = True
        elif row["status"] not in {"post_processing", "completed", "aborted"}:
            raise AppError(409, "state_conflict", "当前会话不能结束。")
        current = await owned_session(db, session_id, identity, lock=False)
    if changed:
        await _clear_checkpoint(session_id)
        await _changed(session_id)
    return SessionView.model_validate(dict(current))


async def terminate_locked(db: AsyncSession, session_id: UUID, reason: str) -> None:
    """The caller holds the session row lock; all interview endings share this rule."""
    stages = await interview_repo.stage_results(db, session_id)
    post = any(stage["result"] == "complete" for stage in stages)
    await interview_repo.terminate_interview(db, session_id, reason, post)


async def put_feedback(
    db: AsyncSession,
    identity: Identity,
    session_id: UUID,
    turn_no: int,
    value: str,
    reason: str | None,
) -> FeedbackView:
    if value == "upvote" and reason is not None:
        raise AppError(400, "invalid_request", "好评不填写差评原因。")
    if (
        value == "downvote"
        and reason is not None
        and reason not in {"重复", "不相关", "表述不清", "其他"}
    ):
        raise AppError(400, "invalid_request", "请选择差评原因。")
    async with db.begin():
        row = await owned_session(db, session_id, identity, lock=True)
        if row["status"] != "interviewing":
            raise AppError(409, "feedback_frozen", "面试结束后不能修改题目反馈。")
        frozen = await db.scalar(
            text("SELECT feedback_frozen_at FROM app.interview_sessions WHERE id = :id"),
            {"id": session_id},
        )
        if frozen is not None:
            raise AppError(409, "feedback_frozen", "题目反馈已经冻结。")
        turn = await interview_repo.get_turn(db, session_id, turn_no)
        if turn is None:
            raise AppError(404, "turn_not_found", "找不到这道题。")
        await db.execute(
            text("""
            INSERT INTO app.question_feedback (session_id, turn_no, value, reason)
            VALUES (:id, :turn_no, :value, :reason)
            ON CONFLICT (session_id, turn_no) DO UPDATE
            SET value = EXCLUDED.value, reason = EXCLUDED.reason, updated_at = now()
        """),
            {"id": session_id, "turn_no": turn_no, "value": value, "reason": reason},
        )
    return FeedbackView(value=value, reason=reason)


async def settle(session_id: UUID) -> None:
    async with session_factory() as db, db.begin():
        row = (
            (
                await db.execute(
                    text("""
            SELECT status, feedback_frozen_at FROM app.interview_sessions
            WHERE id = :id FOR UPDATE
        """),
                    {"id": session_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["status"] not in {"post_processing", "completed", "aborted"}:
            return
        if row["feedback_frozen_at"] is None:
            raise AppError(409, "state_conflict", "反馈尚未冻结。")
        await repo.settle(db, session_id)


async def result_view(db: AsyncSession, identity: Identity, session_id: UUID) -> ResultView:
    async with db.begin():
        row = await owned_session(db, session_id, identity, lock=False)
        stored_plan = await prepare_repo.get_plan(db, session_id)
        turn_rows = await repo.turns(db, session_id)
        report = await repo.get_report(db, session_id)
        complete_stages = await interview_repo.stage_results(db, session_id)
        eligible_for_report = any(stage["result"] == "complete" for stage in complete_stages)
        incomplete = row["status"] == "completed" and eligible_for_report and report is None
    return ResultView(
        session=SessionView.model_validate(dict(row)),
        plan=InterviewPlan.model_validate(stored_plan) if stored_plan else None,
        turns=[
            ResultTurn(
                turn_no=t["turn_no"],
                stage_index=t["stage_index"],
                question=t["question"],
                answer=t["answer"],
                interviewer_message=t["interviewer_message"],
                project_answer=t["project_answer"],
                ideal_answer=t["ideal_answer"],
                comment=t["comment"],
                feedback=FeedbackView(value=t["feedback_value"], reason=t["feedback_reason"])
                if t["feedback_value"]
                else None,
            )
            for t in turn_rows
        ],
        report=Report.model_validate(report) if report else None,
        processing_incomplete=incomplete,
    )


async def snapshot_markdown(db: AsyncSession, identity: Identity, session_id: UUID) -> str:
    async with db.begin():
        await owned_session(db, session_id, identity, lock=False)
        snapshot = await prepare_repo.get_snapshot(db, session_id)
    if snapshot is None:
        raise AppError(404, "snapshot_not_found", "当前会话没有项目快照。")
    return snapshot


class FinalizationState(TypedDict, total=False):
    session_id: UUID
    route: str


async def _call_model(
    model: ModelAdapter,
    session_id: UUID,
    operation: str,
    prompt: str,
    payload: dict,
    schema: type[StrictModel],
) -> StrictModel:
    settings = get_settings()
    return await model.generate_structured(
        session_id=session_id,
        operation=operation,
        messages=[
            Message(role="system", content=(PROMPTS / prompt).read_text(encoding="utf-8")),
            Message(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ],
        output_schema=schema,
        prompt_version="v1",
        retry_policy=RetryPolicy(max_attempts=3, deadline_seconds=settings.model_timeout_seconds),
    )


async def _run_task(session_id: UUID, kind: str, turn_no: int | None, work, publish) -> str:
    owner = str(uuid4())
    async with session_factory() as db, db.begin():
        row = (
            (
                await db.execute(
                    text("""
            SELECT status FROM app.interview_sessions WHERE id = :id FOR UPDATE
        """),
                    {"id": session_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["status"] != "post_processing":
            return "stopped"
        if not await repo.claim_task(db, session_id, kind, turn_no, owner):
            return await repo.task_status(db, session_id, kind, turn_no) or "pending"
    try:
        value = await work()
        async with session_factory() as db, db.begin():
            row = (
                (
                    await db.execute(
                        text("""
                SELECT status FROM app.interview_sessions WHERE id = :id FOR UPDATE
            """),
                        {"id": session_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None or row["status"] != "post_processing":
                return "stopped"
            # Lock task before writing the artifact. A stale lease cannot publish.
            active = await db.scalar(
                text("""
                SELECT 1 FROM app.post_tasks WHERE task_key = :key AND status = 'running'
                  AND lease_owner = :owner AND lease_expires_at > now() FOR UPDATE
            """),
                {
                    "key": f"{session_id}:{kind}" + (f":{turn_no}" if turn_no is not None else ""),
                    "owner": owner,
                },
            )
            if not active:
                return "running"
            await publish(db, value)
            await repo.finish_task(db, session_id, kind, turn_no, owner)
        await _changed(session_id)
        return "succeeded"
    except Exception as exc:  # noqa: BLE001 - isolate independently retried task
        code = exc.code if isinstance(exc, (AppError, ModelFailure)) else "post_task_failed"
        logger.warning("post_task_failed kind=%s code=%s", kind, code)
        async with session_factory() as db, db.begin():
            await repo.finish_task(db, session_id, kind, turn_no, owner, error=code)
        await _changed(session_id)
        return "failed"


async def _project_answers(session_id: UUID, model: ModelAdapter) -> str:
    async with session_factory() as db, db.begin():
        row = (
            (
                await db.execute(
                    text("SELECT source_handle FROM app.interview_sessions WHERE id = :id"),
                    {"id": session_id},
                )
            )
            .mappings()
            .one()
        )
        snapshot = await prepare_repo.get_snapshot(db, session_id)
        answered = [t for t in await repo.turns(db, session_id) if t["answer"] is not None]
    assert snapshot is not None
    payload = {
        "snapshot": snapshot,
        "turns": [
            {
                "turn_no": t["turn_no"],
                "question": _safe(t["question"], 1000),
                "answer": _safe(t["answer"], 8000),
            }
            for t in answered
        ],
    }

    async def work() -> tuple[list[ProjectAnswerItem], str | None]:
        result = None
        handle = row["source_handle"]
        if handle and get_settings().desktop_instance_token:
            try:
                settings = get_settings()
                async with httpx.AsyncClient(timeout=190, trust_env=False) as client:
                    response = await client.post(
                        f"{settings.local_runtime_url}/v1/sources/{handle}:project-answers",
                        headers={"Authorization": f"Bearer {settings.desktop_instance_token}"},
                        json={
                            "session_id": str(session_id),
                            "operation_id": str(
                                uuid5(NAMESPACE_URL, f"{session_id}:project_answers")
                            ),
                            "snapshot": snapshot,
                            "turns": payload["turns"],
                        },
                    )
                    response.raise_for_status()
                    result = ProjectAnswers.model_validate(response.json())
            except Exception:  # noqa: BLE001 - local source is optional
                logger.warning("project_answers_local_fallback")
        if result is None:
            result = await _call_model(
                model, session_id, "project_answers", "project_v1.md", payload, ProjectAnswers
            )
        valid: list[ProjectAnswerItem] = []
        counts: dict[int, int] = {}
        for item in result.answers:
            if isinstance(item.get("turn_no"), int):
                number = item["turn_no"]
                counts[number] = counts.get(number, 0) + 1
        known = {t["turn_no"] for t in answered}
        for item in result.answers:
            try:
                parsed = ProjectAnswerItem.model_validate(item)
                if parsed.turn_no in known and counts.get(parsed.turn_no) == 1:
                    valid.append(
                        ProjectAnswerItem(
                            turn_no=parsed.turn_no,
                            project_answer=_safe(parsed.project_answer, 8000),
                        )
                    )
            except Exception:  # noqa: BLE001 - invalid item does not poison valid siblings
                logger.warning("project_answer_item_rejected")
                continue
        append = (
            _safe(result.post_verification_append, 4000)
            if result.post_verification_append
            else None
        )
        if append and not valid:
            raise AppError(422, "output_invalid", "事后核验缺少对应的有效项目答案。")
        return valid, append

    async def publish(db: AsyncSession, value: tuple[list[ProjectAnswerItem], str | None]) -> None:
        answers, append = value
        if append:
            from app.services.prepare import append_to_section

            key = f"session:{session_id}:post_verification"
            receipt = await prepare_repo.get_append_receipt(db, key)
            digest = hashlib.sha256(append.encode()).hexdigest()
            if receipt is not None and receipt["payload_hash"] != digest:
                raise AppError(409, "state_conflict", "事后核验内容与已提交回执不一致。")
            if receipt is None:
                current = await prepare_repo.get_snapshot(db, session_id)
                assert current is not None
                updated = append_to_section(current, "事后核验", append)
                if len(updated) > 200_000:
                    raise AppError(422, "safety_filter_rejected", "快照已达到长度上限。")
                await db.execute(
                    text("""
                    INSERT INTO app.snapshot_append_operations
                        (operation_key, session_id, section, payload_hash)
                    VALUES (:key, :id, '事后核验', :digest)
                """),
                    {
                        "key": key,
                        "id": session_id,
                        "digest": digest,
                    },
                )
                await prepare_repo.replace_snapshot(db, session_id, updated)
        for answer in answers:
            await repo.write_turn_result(
                db, session_id, answer.turn_no, "project_answer", answer.project_answer
            )

    return await _run_task(session_id, "project_answers", None, work, publish)


async def _ideal_answer(session_id: UUID, turn: dict, model: ModelAdapter) -> str:
    turn_no = turn["turn_no"]

    async def work() -> str:
        async with session_factory() as db, db.begin():
            existing = await repo.ideal_from_bank(db, turn["question_id"])
        if existing:
            return _safe(existing, 8000)
        result = await _call_model(
            model,
            session_id,
            "ideal_answer",
            "ideal_v1.md",
            {"question": _safe(turn["question"], 1000)},
            IdealAnswer,
        )
        return _safe(result.ideal_answer, 8000)

    async def publish(db: AsyncSession, value: str) -> None:
        await repo.write_turn_result(db, session_id, turn_no, "ideal_answer", value)

    return await _run_task(session_id, "ideal_answer", turn_no, work, publish)


async def _evaluation(session_id: UUID, turn_no: int, model: ModelAdapter) -> str:
    async with session_factory() as db, db.begin():
        snapshot = await prepare_repo.get_snapshot(db, session_id)
        turn = next(t for t in await repo.turns(db, session_id) if t["turn_no"] == turn_no)

    async def work() -> str:
        result = await _call_model(
            model,
            session_id,
            "evaluation",
            "evaluation_v1.md",
            {
                "snapshot": snapshot,
                "question": _safe(turn["question"], 1000),
                "answer": _safe(turn["answer"], 8000),
                "project_answer": turn["project_answer"],
                "ideal_answer": turn["ideal_answer"],
            },
            TurnEvaluation,
        )
        return _safe(result.comment, 8000)

    async def publish(db: AsyncSession, value: str) -> None:
        await repo.write_turn_result(db, session_id, turn_no, "comment", value)

    return await _run_task(session_id, "evaluation", turn_no, work, publish)


async def _report(session_id: UUID, model: ModelAdapter) -> str:
    async with session_factory() as db, db.begin():
        snapshot = await prepare_repo.get_snapshot(db, session_id)
        plan_json = await prepare_repo.get_plan(db, session_id)
        turns = [t for t in await repo.turns(db, session_id) if t["answer"] is not None]
    plan = InterviewPlan.model_validate(plan_json)
    payload = {
        "snapshot": snapshot,
        "turns": [
            {
                "stage": plan.stages[t["stage_index"]].title,
                "question": _safe(t["question"], 1000),
                "answer": _safe(t["answer"], 8000),
                "comment": t["comment"],
            }
            for t in turns
        ],
    }

    async def work() -> Report:
        value = await _call_model(model, session_id, "report", "report_v1.md", payload, Report)
        data = value.model_dump()
        data["overall"] = _safe(data["overall"], 8000)
        data["project_recommendations"] = _safe(data["project_recommendations"], 8000)
        data["training_recommendations"] = _safe(data["training_recommendations"], 8000)
        for dim in data["dimensions"].values():
            dim["analysis"] = _safe(dim["analysis"], 8000)
        return Report.model_validate(data)

    async def publish(db: AsyncSession, value: Report) -> None:
        await repo.write_report(db, session_id, value.model_dump_json())

    return await _run_task(session_id, "report", None, work, publish)


async def run_finalization(session_id: UUID, model: ModelAdapter) -> None:
    """The graph alone orders task dependencies; task rows are only a ledger."""

    async def load(_state: FinalizationState) -> FinalizationState:
        async with session_factory() as db, db.begin():
            status = await db.scalar(
                text("SELECT status FROM app.interview_sessions WHERE id = :id"), {"id": session_id}
            )
        return {"route": "continue" if status == "post_processing" else "stop"}

    async def settle_node(_state: FinalizationState) -> FinalizationState:
        await settle(session_id)
        return {"route": "continue"}

    async def references(_state: FinalizationState) -> FinalizationState:
        async with session_factory() as db, db.begin():
            answered = [
                dict(t) for t in await repo.turns(db, session_id) if t["answer"] is not None
            ]
        states = await asyncio.gather(
            _project_answers(session_id, model),
            *(_ideal_answer(session_id, t, model) for t in answered),
        )
        return {
            "route": "continue" if all(s in {"succeeded", "failed"} for s in states) else "stop"
        }

    async def evaluations(_state: FinalizationState) -> FinalizationState:
        async with session_factory() as db, db.begin():
            answered = [
                t["turn_no"] for t in await repo.turns(db, session_id) if t["answer"] is not None
            ]
        states = await asyncio.gather(*(_evaluation(session_id, no, model) for no in answered))
        if not all(s in {"succeeded", "failed"} for s in states):
            return {"route": "stop"}
        return {"route": "report" if all(s == "succeeded" for s in states) else "complete"}

    async def report_node(_state: FinalizationState) -> FinalizationState:
        state = await _report(session_id, model)
        return {"route": "complete" if state in {"succeeded", "failed"} else "stop"}

    async def complete(_state: FinalizationState) -> FinalizationState:
        async with session_factory() as db, db.begin():
            await db.execute(
                text("""
                UPDATE app.interview_sessions SET status = 'completed', completed_at = now(),
                    updated_at = now() WHERE id = :id AND status = 'post_processing'
            """),
                {"id": session_id},
            )
        await _clear_checkpoint(session_id)
        await _changed(session_id)
        return {"route": "stop"}

    graph = StateGraph(FinalizationState)
    for name, node in (
        ("load", load),
        ("settle", settle_node),
        ("references", references),
        ("evaluations", evaluations),
        ("report", report_node),
        ("complete", complete),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "load")
    graph.add_conditional_edges("load", lambda s: s["route"], {"continue": "settle", "stop": END})
    graph.add_edge("settle", "references")
    graph.add_conditional_edges(
        "references", lambda s: s["route"], {"continue": "evaluations", "stop": END}
    )
    graph.add_conditional_edges(
        "evaluations",
        lambda s: s["route"],
        {"report": "report", "complete": "complete", "stop": END},
    )
    graph.add_conditional_edges(
        "report", lambda s: s["route"], {"complete": "complete", "stop": END}
    )
    graph.add_edge("complete", END)
    await graph.compile().ainvoke({"session_id": session_id})
