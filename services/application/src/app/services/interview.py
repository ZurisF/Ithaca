"""Live interview commands; PostgreSQL publishes facts, Redis holds interrupts."""

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from pydantic import Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.bank.retrieval import QuestionCandidate, QuestionRetriever
from app.domain.access import Identity
from app.domain.contracts import (
    InterviewPlan,
    InterviewView,
    SectionRef,
    SessionView,
    StrictModel,
    SupervisorDecision,
    TurnView,
)
from app.domain.rules import exact_question_id, parse_sections
from app.repositories import interview as repo
from app.repositories import prepare as prepare_repo
from app.services.errors import AppError
from app.services.interview_checkpoint import (
    delete_checkpoint,
    execution_lock,
    notify_current_changed,
    read_checkpoint,
    write_checkpoint,
    write_compact,
)
from app.services.planning import load_planning_assets, validate_plan_against_assets
from app.services.session_access import owned_session, require_preparing
from app.settings import get_settings
from content_safety import ContentRejected, filter_text
from model_adapter import Message, ModelAdapter, ModelFailure, RetryPolicy

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[5]
PROMPT = ROOT / "packages/prompt_assets/prompts/supervisor/v1.md"
ANSWER_PROMPT = ROOT / "packages/prompt_assets/prompts/supervisor/answer_v1.md"
COMPACT_PROMPT = ROOT / "packages/prompt_assets/prompts/compact/v1.md"


@dataclass(frozen=True)
class Trigger:
    stage_index: int
    answered_turn_no: int | None
    next_turn_no: int

    @property
    def kind(self) -> str:
        return "answered_turn" if self.answered_turn_no is not None else "stage_entry"


class CompactResult(StrictModel):
    compact: str = Field(min_length=1, max_length=12_000)


class InterviewGraphState(TypedDict, total=False):
    snapshot: str
    plan: InterviewPlan
    latest: object
    trigger: Trigger
    checkpoint: dict | None
    compact: str | None
    recent: list[dict]
    candidates: list[QuestionCandidate]
    decision: SupervisorDecision
    route: str


def _working_text(raw: str, *, max_chars: int = 8_000) -> str:
    try:
        return filter_text(raw, max_chars=max_chars).text
    except ContentRejected as exc:
        raise AppError(422, "safety_filter_rejected", "回答未通过内容安全检查。") from exc


def _sanitized_decision(value: SupervisorDecision) -> SupervisorDecision:
    data = value.model_dump()
    if data["question"] is not None:
        data["question"] = _working_text(data["question"], max_chars=1_000)
    if data["interviewer_message"] is not None:
        data["interviewer_message"] = _working_text(data["interviewer_message"], max_chars=1_000)
    for act in data["user_acts"]:
        if act["type"] == "correct_project_fact":
            act["text"] = _working_text(act["text"], max_chars=4_000)
    return SupervisorDecision.model_validate(data)


def _trigger(latest, stage_index: int | None) -> Trigger | None:
    if stage_index is None or (latest is not None and latest["answer"] is None):
        return None
    turn_no = latest["turn_no"] if latest else 0
    if latest is not None and latest["stage_index"] == stage_index:
        return Trigger(stage_index, turn_no, turn_no + 1)
    if latest is None or latest["stage_index"] < stage_index:
        return Trigger(stage_index, None, turn_no + 1)
    return None


def _trigger_matches(trigger: Trigger, latest, stage_index: int | None) -> bool:
    return _trigger(latest, stage_index) == trigger


def _active_interrupt(checkpoint: dict | None, trigger: Trigger | None) -> str | None:
    if not checkpoint or trigger is None:
        return None
    awaiting = checkpoint.get("awaiting")
    if awaiting == "decision_retry":
        return awaiting
    if awaiting == "snapshot_confirmation":
        try:
            pending_trigger = Trigger(**checkpoint["pending"]["trigger"])
        except (KeyError, TypeError, ValueError):
            return None
        return awaiting if pending_trigger == trigger else None
    return None


async def get_current_view(db: AsyncSession, identity: Identity, session_id: UUID) -> InterviewView:
    async with db.begin():
        row = await owned_session(db, session_id, identity, lock=False)
        stored_plan = await prepare_repo.get_plan(db, session_id)
        plan = InterviewPlan.model_validate(stored_plan) if stored_plan else None
        stage_index = (
            await repo.first_open_stage(db, session_id, len(plan.stages)) if plan else None
        )
        latest = await repo.latest_turn(db, session_id)
        previous = (
            await repo.get_turn(db, session_id, latest["turn_no"] - 1)
            if latest is not None and latest["turn_no"] > 1
            else None
        )
        trigger = _trigger(latest, stage_index)
    try:
        checkpoint = await read_checkpoint(session_id) if row["status"] == "interviewing" else None
    except Exception:  # noqa: BLE001 - PG remains the published business view
        checkpoint = None
        logger.warning("interview_checkpoint_read_failed")
    awaiting = None
    pending_correction = None
    if row["status"] == "interviewing":
        if latest is not None and latest["answer"] is None:
            awaiting = "answer"
        else:
            awaiting = _active_interrupt(checkpoint, trigger)
        if awaiting == "snapshot_confirmation":
            pending_correction = (checkpoint or {}).get("pending", {}).get("correction")
    return InterviewView(
        session=SessionView.model_validate(dict(row)),
        plan=plan,
        current_stage_index=stage_index,
        current_turn=TurnView.model_validate(dict(latest)) if latest else None,
        previous_turn=TurnView.model_validate(dict(previous)) if previous else None,
        awaiting=awaiting,
        pending_correction=pending_correction,
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
    errors = validate_plan_against_assets(
        plan, row["interview_direction"], selected, load_planning_assets()
    )
    if errors:
        raise AppError(409, "plan_invalid", "当前面试计划已失效，请重新生成。")


async def _load_context(db: AsyncSession, identity: Identity, session_id: UUID):
    async with db.begin():
        row = await owned_session(db, session_id, identity, lock=False)
        stored = await prepare_repo.get_plan(db, session_id)
        plan = InterviewPlan.model_validate(stored) if stored else None
        snapshot = await prepare_repo.get_snapshot(db, session_id)
        latest = await repo.latest_turn(db, session_id)
        turns = await repo.turns_for_context(db, session_id)
        stage_index = (
            await repo.first_open_stage(db, session_id, len(plan.stages)) if plan else None
        )
    return row, snapshot, plan, latest, turns, _trigger(latest, stage_index)


async def _recent_context(
    session_id: UUID, turns: list, checkpoint: dict | None, model: ModelAdapter
) -> tuple[str | None, list[dict]]:
    """Build bounded model history; checkpoint and its cursor advance together."""
    answered = [turn for turn in turns if turn["answer"] is not None]
    cursor = int((checkpoint or {}).get("compacted_through_turn_no") or 0)
    compact = (checkpoint or {}).get("compact")
    if cursor > len(answered) or (cursor and not compact):
        cursor, compact = 0, None
    settings = get_settings()
    while len(answered) - cursor >= 20:
        batch = answered[cursor : cursor + 20]
        filtered = [
            {
                "turn_no": turn["turn_no"],
                "stage_index": turn["stage_index"],
                "question": _working_text(turn["question"], max_chars=1_000),
                "answer": _working_text(turn["answer"]),
                "interviewer_message": turn["interviewer_message"],
            }
            for turn in batch
        ]
        try:
            result = await model.generate_structured(
                session_id=session_id,
                operation="interview_compact",
                messages=[
                    Message(role="system", content=COMPACT_PROMPT.read_text(encoding="utf-8")),
                    Message(
                        role="user",
                        content=json.dumps(
                            {"previous_compact": compact, "turns": filtered}, ensure_ascii=False
                        ),
                    ),
                ],
                output_schema=CompactResult,
                prompt_version="v1",
                retry_policy=RetryPolicy(
                    max_attempts=settings.model_max_attempts,
                    deadline_seconds=settings.model_timeout_seconds,
                ),
            )
            safe_compact = _working_text(result.compact, max_chars=12_000)
            await write_compact(session_id, compact=safe_compact, through_turn_no=cursor + 20)
        except Exception:  # noqa: BLE001 - old compact and original turns remain
            logger.warning("interview_compact_failed")
            break
        compact, cursor = safe_compact, cursor + 20
    recent = [
        {
            "turn_no": turn["turn_no"],
            "stage_index": turn["stage_index"],
            "question": _working_text(turn["question"], max_chars=1_000),
            "answer": _working_text(turn["answer"]) if turn["answer"] is not None else None,
            "interviewer_message": turn["interviewer_message"],
        }
        for turn in turns
        if turn["turn_no"] > cursor
    ]
    return compact, recent


async def _publish_decision(
    db: AsyncSession,
    identity: Identity,
    session_id: UUID,
    trigger: Trigger,
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
        stage_index = await repo.first_open_stage(db, session_id, len(plan.stages))
        latest = await repo.latest_turn(db, session_id)
        if not _trigger_matches(trigger, latest, stage_index):
            return False
        if decision.plan_action == "continue":
            if trigger.next_turn_no > 100:
                from app.services.finalization import terminate_locked

                await terminate_locked(db, session_id, "safety_cap")
                return True
            question_id = exact_question_id(
                decision.question or "",
                ((item.question_id, item.question) for item in candidates),
            )
            return await repo.publish_next_turn(
                db,
                session_id,
                trigger.next_turn_no,
                trigger.stage_index,
                decision.question or "",
                question_id,
                answered_turn_no=trigger.answered_turn_no,
                interviewer_message=decision.interviewer_message,
            )
        if trigger.answered_turn_no is None:
            return False
        published = await repo.close_stage(
            db,
            session_id,
            trigger.stage_index,
            plan.stages[trigger.stage_index].id,
            decision.plan_action,
            trigger.answered_turn_no,
            decision.interviewer_message,
        )
        if published and trigger.stage_index == len(plan.stages) - 1:
            from app.services.finalization import terminate_locked

            await terminate_locked(db, session_id, "normal")
        return published


async def _notify(session_id: UUID) -> None:
    try:
        await notify_current_changed(session_id)
    except Exception:  # noqa: BLE001 - notification is disposable
        logger.warning("interview_notification_failed")


async def _run_decisions(
    db: AsyncSession,
    identity: Identity,
    session_id: UUID,
    model: ModelAdapter,
    retriever: QuestionRetriever,
) -> InterviewView:
    """Run the interview graph to the next user or failure interrupt."""
    loaded_turns: list[dict] = []

    async def load_session_context(_state: InterviewGraphState) -> InterviewGraphState:
        nonlocal loaded_turns
        row, snapshot, plan, _latest, turns, trigger = await _load_context(db, identity, session_id)
        if row["status"] != "interviewing" or trigger is None or snapshot is None or plan is None:
            return {"route": "stop"}
        checkpoint = await read_checkpoint(session_id)
        if _active_interrupt(checkpoint, trigger):
            return {"route": "stop"}
        safe_turns = [
            {
                "turn_no": turn["turn_no"],
                "stage_index": turn["stage_index"],
                "question": _working_text(turn["question"], max_chars=1_000),
                "answer": _working_text(turn["answer"]) if turn["answer"] is not None else None,
                "interviewer_message": turn["interviewer_message"],
            }
            for turn in turns
        ]
        safe_latest = safe_turns[-1] if safe_turns else None
        loaded_turns = safe_turns
        return {
            "snapshot": snapshot,
            "plan": plan,
            "latest": safe_latest,
            "trigger": trigger,
            "checkpoint": checkpoint,
            "route": "continue",
        }

    async def maybe_compact(state: InterviewGraphState) -> InterviewGraphState:
        checkpoint = state["checkpoint"]
        compact, recent = await _recent_context(session_id, loaded_turns, checkpoint, model)
        return {"compact": compact, "recent": recent}

    async def retrieve_candidates(state: InterviewGraphState) -> InterviewGraphState:
        trigger = state["trigger"]
        latest = state["latest"]
        plan = state["plan"]
        stage = plan.stages[trigger.stage_index]
        query = stage.goal
        if trigger.answered_turn_no is not None and latest is not None:
            query = f"{stage.goal}\n{_working_text(latest['answer'])[:2_000]}"
        settings = get_settings()
        try:
            candidates = await retriever.retrieve_for_turn(
                session_id, query, stage.topic_path, settings.retrieval_limit
            )
        except Exception:  # noqa: BLE001 - retrieval degrades to no candidates
            logger.warning("interview_retrieval_failed")
            candidates = []
        return {"candidates": candidates}

    async def call_supervisor(state: InterviewGraphState) -> InterviewGraphState:
        trigger = state["trigger"]
        latest = state["latest"]
        plan = state["plan"]
        stage = plan.stages[trigger.stage_index]
        payload = {
            "snapshot": state["snapshot"],
            "current_stage": stage.model_dump(mode="json"),
            "current_stage_index": trigger.stage_index,
            "trigger": trigger.kind,
            "current_answered_turn": {
                "turn_no": latest["turn_no"],
                "question": _working_text(latest["question"], max_chars=1_000),
                "answer": _working_text(latest["answer"]),
            }
            if trigger.answered_turn_no is not None and latest is not None
            else None,
            "actions": ["continue", "complete", "unresolved"],
            "compact": state["compact"],
            "recent_turns": state["recent"],
            "retrieved_questions": [item.question for item in state["candidates"]],
        }

        def validate(value: SupervisorDecision, current_trigger: Trigger = trigger) -> list[str]:
            if current_trigger.kind == "stage_entry":
                try:
                    value.validate_stage_entry()
                except ValueError:
                    return [
                        "stage entry requires continue, no user acts and no interviewer message"
                    ]
            if sum(act.type == "correct_project_fact" for act in value.user_acts) > 1:
                return ["only one project fact correction may be proposed per answer"]
            return []

        try:
            settings = get_settings()
            decision = await model.generate_structured(
                session_id=session_id,
                operation="supervisor_stage_entry"
                if trigger.kind == "stage_entry"
                else "supervisor_answer",
                messages=[
                    Message(
                        role="system",
                        content=(
                            PROMPT if trigger.kind == "stage_entry" else ANSWER_PROMPT
                        ).read_text(encoding="utf-8"),
                    ),
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
            # Controlled adapters must pass the same deterministic barrier as production.
            if validate(decision):
                raise ModelFailure("output_invalid")
            decision = _sanitized_decision(decision)
        except AppError as exc:
            await write_checkpoint(session_id, awaiting="decision_retry", error="output_invalid")
            await _notify(session_id)
            logger.warning("supervisor_output_rejected code=%s", exc.code)
            return {"route": "stop"}
        except ModelFailure as exc:
            await write_checkpoint(session_id, awaiting="decision_retry", error=exc.code)
            await _notify(session_id)
            return {"route": "stop"}
        return {"decision": decision, "route": "continue"}

    async def apply_supervisor_decision(state: InterviewGraphState) -> InterviewGraphState:
        trigger = state["trigger"]
        decision = state["decision"]
        candidates = state["candidates"]
        corrections = [act for act in decision.user_acts if act.type == "correct_project_fact"]
        if corrections and trigger.answered_turn_no is not None:
            key = f"session:{session_id}:turn:{trigger.answered_turn_no}:snapshot_correction"
            async with db.begin():
                already_confirmed = await prepare_repo.get_append_receipt(db, key)
            if already_confirmed is not None:
                corrections = []
        if corrections and trigger.answered_turn_no is not None:
            correction = _working_text(corrections[0].text, max_chars=4_000)
            pending = {
                "trigger": {
                    "stage_index": trigger.stage_index,
                    "answered_turn_no": trigger.answered_turn_no,
                    "next_turn_no": trigger.next_turn_no,
                },
                "decision": decision.model_dump(mode="json"),
                "candidates": [
                    {"question_id": str(item.question_id), "question": item.question}
                    for item in candidates
                ],
                "correction": correction,
            }
            await write_checkpoint(session_id, awaiting="snapshot_confirmation", pending=pending)
            await _notify(session_id)
            return {"route": "stop"}

        published = await _publish_decision(
            db,
            identity,
            session_id,
            trigger,
            state["snapshot"],
            state["plan"],
            candidates,
            decision,
        )
        if not published:
            return {"route": "stop"}
        if decision.plan_action == "continue" and trigger.next_turn_no <= 100:
            try:
                await write_checkpoint(session_id, awaiting="answer")
            except Exception:  # noqa: BLE001 - PG turn is authoritative
                logger.warning("interview_checkpoint_write_failed_after_publish")
            await _notify(session_id)
            return {"route": "stop"}
        current = await get_current_view(db, identity, session_id)
        if current.session.status != "interviewing":
            try:
                await delete_checkpoint(session_id)
            except Exception:  # noqa: BLE001 - terminal PG status is authoritative
                logger.warning("terminal_checkpoint_delete_failed")
            await _notify(session_id)
            return {"route": "stop"}
        await write_checkpoint(session_id, awaiting="processing")
        await _notify(session_id)
        return {"route": "next_stage"}

    graph = StateGraph(InterviewGraphState)
    graph.add_node("load_session_context", load_session_context)
    graph.add_node("maybe_compact", maybe_compact)
    graph.add_node("retrieve_candidates", retrieve_candidates)
    graph.add_node("call_supervisor", call_supervisor)
    graph.add_node("apply_supervisor_decision", apply_supervisor_decision)
    graph.add_edge(START, "load_session_context")
    graph.add_conditional_edges(
        "load_session_context",
        lambda state: state["route"],
        {"stop": END, "continue": "maybe_compact"},
    )
    graph.add_edge("maybe_compact", "retrieve_candidates")
    graph.add_edge("retrieve_candidates", "call_supervisor")
    graph.add_conditional_edges(
        "call_supervisor",
        lambda state: state["route"],
        {"stop": END, "continue": "apply_supervisor_decision"},
    )
    graph.add_conditional_edges(
        "apply_supervisor_decision",
        lambda state: state["route"],
        {"stop": END, "next_stage": "load_session_context"},
    )
    await graph.compile().ainvoke({"route": "continue"})
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
        return await _run_decisions(db, identity, session_id, model, retriever)


async def answer(
    db: AsyncSession,
    identity: Identity,
    session_id: UUID,
    turn_no: int,
    raw_answer: str,
    model: ModelAdapter,
    retriever: QuestionRetriever,
) -> InterviewView:
    _working_text(raw_answer)
    async with db.begin():
        await owned_session(db, session_id, identity, lock=False)
    async with execution_lock(session_id):
        checkpoint = await read_checkpoint(session_id)
        async with db.begin():
            row = await owned_session(db, session_id, identity, lock=True)
            latest = await repo.latest_turn(db, session_id)
            requested = await repo.get_turn(db, session_id, turn_no)
            if requested is not None and requested["answer"] is not None:
                if requested["answer"] != raw_answer:
                    raise AppError(409, "answer_conflict", "这道题已有不同回答。")
                duplicate = True
            else:
                duplicate = False
                if (
                    latest is not None
                    and latest["answer"] is not None
                    and checkpoint is not None
                    and checkpoint.get("awaiting") in {"snapshot_confirmation", "decision_retry"}
                ):
                    raise AppError(409, "operation_in_progress", "当前面试操作仍在进行。")
                if (
                    row["status"] != "interviewing"
                    or latest is None
                    or latest["turn_no"] != turn_no
                ):
                    raise AppError(409, "state_conflict", "这道题已不再等待回答。")
                if latest["answer"] is not None:
                    raise AppError(409, "answer_conflict", "这道题已有不同回答。")
                if not await repo.answer_current_turn(db, session_id, turn_no, raw_answer):
                    raise AppError(409, "state_conflict", "这道题已不再等待回答。")
        if duplicate:
            return await get_current_view(db, identity, session_id)
        await _notify(session_id)
        return await _run_decisions(db, identity, session_id, model, retriever)


async def retry_decision(
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
        row, _snapshot, _plan, _latest, _turns, trigger = await _load_context(
            db, identity, session_id
        )
        if row["status"] != "interviewing" or trigger is None:
            raise AppError(409, "retry_not_available", "当前没有可重试的面试决策。")
        await write_checkpoint(session_id, awaiting="processing")
        return await _run_decisions(db, identity, session_id, model, retriever)


async def resolve_snapshot_correction(
    db: AsyncSession,
    identity: Identity,
    session_id: UUID,
    turn_no: int,
    decision_value: str,
    edited_text: str | None,
    model: ModelAdapter,
    retriever: QuestionRetriever,
) -> InterviewView:
    async with db.begin():
        await owned_session(db, session_id, identity, lock=False)
    async with execution_lock(session_id):
        checkpoint = await read_checkpoint(session_id)
        if not checkpoint or checkpoint.get("awaiting") != "snapshot_confirmation":
            raise AppError(409, "operation_in_progress", "当前没有待确认的快照更正。")
        pending = checkpoint.get("pending") or {}
        trigger = Trigger(**pending["trigger"])
        if trigger.answered_turn_no != turn_no:
            raise AppError(409, "state_conflict", "更正对应的题目已变化。")
        candidate = pending["correction"]
        if decision_value == "confirm" and edited_text is not None:
            filtered = _working_text(edited_text, max_chars=4_000)
            if filtered != edited_text:
                pending["correction"] = filtered
                await write_checkpoint(
                    session_id, awaiting="snapshot_confirmation", pending=pending
                )
                return await get_current_view(db, identity, session_id)
            candidate = filtered
            pending["correction"] = filtered
            await write_checkpoint(session_id, awaiting="snapshot_confirmation", pending=pending)
        async with db.begin():
            row = await owned_session(db, session_id, identity, lock=True)
            stored = await prepare_repo.get_plan(db, session_id)
            plan = InterviewPlan.model_validate(stored) if stored else None
            snapshot = await prepare_repo.get_snapshot(db, session_id)
            stage_index = (
                await repo.first_open_stage(db, session_id, len(plan.stages)) if plan else None
            )
            latest = await repo.latest_turn(db, session_id)
            if row["status"] != "interviewing" or not _trigger_matches(
                trigger, latest, stage_index
            ):
                raise AppError(409, "state_conflict", "面试已推进，请刷新当前状态。")
            if snapshot is None or plan is None:
                raise AppError(409, "state_conflict", "面试材料不可用。")
            key = f"session:{session_id}:turn:{turn_no}:snapshot_correction"
            receipt = await prepare_repo.get_append_receipt(db, key)
            if decision_value == "do_not_write" and receipt is not None:
                raise AppError(409, "state_conflict", "这条更正已经写入快照。")
            if decision_value == "confirm":
                from app.services.prepare import append_to_section

                digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
                if receipt is None:
                    updated = append_to_section(snapshot, "用户意见", candidate)
                    if len(updated) > 200_000:
                        raise AppError(422, "safety_filter_rejected", "快照已达到长度上限。")
                    await db.execute(
                        text("""
                        INSERT INTO app.snapshot_append_operations
                            (operation_key, session_id, section, payload_hash)
                        VALUES (:key, :session_id, '用户意见', :digest)
                        """),
                        {"key": key, "session_id": session_id, "digest": digest},
                    )
                    await prepare_repo.replace_snapshot(db, session_id, updated)
                    snapshot = updated
                elif receipt["payload_hash"] != digest:
                    raise AppError(409, "answer_conflict", "更正内容已确认，不能再次更改。")
        decision = SupervisorDecision.model_validate(pending["decision"])
        candidates = [
            QuestionCandidate(UUID(item["question_id"]), item["question"])
            for item in pending["candidates"]
        ]
        published = await _publish_decision(
            db, identity, session_id, trigger, snapshot, plan, candidates, decision
        )
        if published:
            if decision.plan_action == "continue" and trigger.next_turn_no <= 100:
                await write_checkpoint(session_id, awaiting="answer")
            else:
                current = await get_current_view(db, identity, session_id)
                if current.session.status != "interviewing":
                    try:
                        await delete_checkpoint(session_id)
                    except Exception:  # noqa: BLE001
                        logger.warning("terminal_checkpoint_delete_failed")
                else:
                    await write_checkpoint(session_id, awaiting="processing")
            await _notify(session_id)
            if decision.plan_action != "continue":
                return await _run_decisions(db, identity, session_id, model, retriever)
        return await get_current_view(db, identity, session_id)
