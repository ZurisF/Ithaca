"""Owner consent and administrator controlled publication into the question bank."""

import json
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.bank.seed import lexical_terms
from app.bank.vectors import checked_vector
from app.domain.access import Identity
from app.domain.contracts import (
    BankQuestion,
    CurationItem,
    CurationQueue,
    CurationSource,
    CurationSuggestion,
    CurationTurn,
    SessionView,
)
from app.repositories import curation as repo
from app.repositories import prepare as prepare_repo
from app.services.errors import AppError
from app.services.session_access import owned_session
from app.settings import get_settings
from content_safety import ContentRejected, filter_text
from model_adapter import Message, ModelAdapter, ModelFailure, RetryPolicy

TOPICS = Path(__file__).resolve().parents[5] / "packages/planning_assets/topics.yaml"
SUGGESTION_PROMPT = (
    Path(__file__).resolve().parents[5] / "packages/prompt_assets/prompts/curation/v1.md"
)


def _topics() -> list[str]:
    return [entry["path"] for entry in json.loads(TOPICS.read_text(encoding="utf-8"))["topics"]]


def _administrator(identity: Identity) -> None:
    if identity.role != "administrator":
        raise AppError(403, "forbidden", "只有 Administrator 可以审核题库材料。")


def _safe_public_text(raw: str, limit: int) -> str:
    try:
        filtered = filter_text(raw, max_chars=limit).text
    except ContentRejected as exc:
        raise AppError(422, "safety_filter_rejected", "公开题目未通过内容安全检查。") from exc
    if filtered != raw:
        raise AppError(422, "safety_filter_rejected", "公开内容含需脱敏信息，请编辑后重新审核。")
    return filtered.strip()


async def grant(
    db: AsyncSession, identity: Identity, session_id: UUID, enabled: bool
) -> SessionView:
    async with db.begin():
        await owned_session(db, session_id, identity, lock=True)
        await db.execute(
            text("""
                UPDATE app.interview_sessions SET curation_review = :enabled, updated_at = now()
                WHERE id = :id
            """),
            {"id": session_id, "enabled": enabled},
        )
        row = await prepare_repo.get_session(db, session_id, identity.id)
    return SessionView.model_validate(dict(row))


async def queue(
    db: AsyncSession,
    identity: Identity,
    *,
    limit: int,
    offset: int,
) -> CurationQueue:
    _administrator(identity)
    sources = await repo.authorized_sources(db, limit, offset)
    ids = [row["session_id"] for row in sources]
    turns = await repo.source_turns(db, ids)
    items = await repo.items(db, ids)
    by_session: dict[UUID, list[CurationTurn]] = {session_id: [] for session_id in ids}
    for row in turns:
        by_session[row["session_id"]].append(
            CurationTurn.model_validate(
                {key: value for key, value in row.items() if key != "session_id"}
            )
        )
    return CurationQueue(
        sources=[
            CurationSource.model_validate({**row, "turns": by_session[row["session_id"]]})
            for row in sources
        ],
        items=[CurationItem.model_validate(dict(row)) for row in items],
        topics=_topics(),
    )


async def save_item(
    db: AsyncSession,
    identity: Identity,
    session_id: UUID,
    turn_no: int,
    *,
    item_id: UUID | None = None,
    status: str | None = None,
    edited_question: str | None = None,
    proposed_topic_path: str | None = None,
    review_notes: str | None = None,
    suggest: bool = False,
    model: ModelAdapter | None = None,
) -> CurationItem:
    _administrator(identity)
    if item_id is None and status is not None:
        raise AppError(400, "invalid_request", "请先选择源问题创建策展条目。")
    if suggest and (item_id is not None or model is None):
        raise AppError(400, "invalid_request", "只能在选择源问题时获取整理建议。")
    if item_id is not None and status not in {"reviewed", "rejected"}:
        raise AppError(400, "invalid_request", "审核状态无效。")
    if item_id is not None and status == "reviewed":
        if not edited_question or not proposed_topic_path or not review_notes:
            raise AppError(400, "invalid_request", "请填写公开题目、Topic 和人工审核备注。")
        edited_question = _safe_public_text(edited_question, 1000)
        if not edited_question:
            raise AppError(400, "invalid_request", "公开题目不能为空。")
        if proposed_topic_path not in _topics():
            raise AppError(400, "invalid_request", "Topic 不在正式列表中。")
    async with db.begin():
        if await repo.source(db, session_id, lock=True) is None:
            raise AppError(404, "curation_not_granted", "材料未获授权或尚未结束。")
        if item_id is None:
            if not await repo.turn_exists(db, session_id, turn_no):
                raise AppError(404, "turn_not_found", "找不到源问题。")
            item_id = uuid4()
            await repo.insert_item(db, item_id, session_id, turn_no)
            source_material = await repo.source_turn(db, session_id, turn_no) if suggest else None
        else:
            existing = await repo.item(db, item_id)
            if (
                existing is None
                or existing["source_session_id"] != session_id
                or existing["source_turn_no"] != turn_no
            ):
                raise AppError(404, "curation_not_granted", "找不到已授权的策展条目。")
            if existing["status"] == "added":
                raise AppError(409, "state_conflict", "已入库条目不能再次编辑。")
            await repo.review_item(
                db,
                item_id,
                status,
                edited_question or "",
                proposed_topic_path or "",
                review_notes or "",
                identity.id,
            )
        row = await repo.item(db, item_id)
    item_view = CurationItem.model_validate(dict(row))
    settings = get_settings()
    if not suggest or not settings.model_api_key or not settings.model_name:
        return item_view

    def validate_suggestion(candidate: CurationSuggestion) -> list[str]:
        errors = []
        if candidate.proposed_topic_path not in _topics():
            errors.append("topic is not in the registry")
        for value in (candidate.edited_question, candidate.ideal_answer):
            if value:
                try:
                    if filter_text(value, max_chars=8000).changed:
                        errors.append("public content contains sensitive tokens")
                except ContentRejected:
                    errors.append("public content failed safety validation")
        return errors

    try:
        suggestion = await model.generate_structured(
            session_id=session_id,
            operation="curation_suggestion",
            messages=[
                Message(role="system", content=SUGGESTION_PROMPT.read_text(encoding="utf-8")),
                Message(
                    role="user",
                    content=json.dumps(
                        {
                            "question": source_material["question"],
                            "answer": source_material["answer"],
                            "feedback_value": source_material["feedback_value"],
                            "feedback_reason": source_material["feedback_reason"],
                            "topics": _topics(),
                        },
                        ensure_ascii=False,
                    ),
                ),
            ],
            output_schema=CurationSuggestion,
            prompt_version="v1",
            retry_policy=RetryPolicy(
                max_attempts=settings.model_max_attempts,
                deadline_seconds=settings.model_timeout_seconds,
            ),
            validate_output=validate_suggestion,
        )
    except ModelFailure as exc:
        raise AppError(
            503, "model_call_failed", "整理建议暂时不可用，可继续人工审核。", True
        ) from exc
    async with db.begin():
        if await repo.source(db, session_id) is None:
            raise AppError(404, "curation_not_granted", "材料授权已撤销。")
    return item_view.model_copy(update={"suggestion": suggestion})


async def publish(
    db: AsyncSession,
    identity: Identity,
    item_id: UUID,
    ideal_answer: str | None,
    embedder,
) -> CurationItem:
    _administrator(identity)
    async with db.begin():
        initial = await repo.item(db, item_id)
        if initial is None:
            raise AppError(404, "curation_not_granted", "找不到已授权的策展条目。")
        if initial["status"] != "reviewed":
            raise AppError(409, "state_conflict", "请先完成人工审核。")
        question = initial["edited_question"]
        topic = initial["proposed_topic_path"]
    answer = _safe_public_text(ideal_answer, 8000) if ideal_answer else None
    try:
        embedding = checked_vector(await embedder.embed_document(question))
    except Exception as exc:
        raise AppError(
            503, "dependency_unavailable", "题目索引生成失败，请稍后重试。", True
        ) from exc
    async with db.begin():
        if await repo.source(db, initial["source_session_id"], lock=True) is None:
            raise AppError(404, "curation_not_granted", "材料授权已撤销。")
        current = await repo.item(db, item_id)
        if (
            current is None
            or current["status"] != "reviewed"
            or current["edited_question"] != question
            or current["proposed_topic_path"] != topic
        ):
            raise AppError(409, "state_conflict", "审核内容已经变化，请重新确认。")
        question_id = uuid4()
        if not await repo.insert_question(
            db, question_id, question, topic, answer, embedding, lexical_terms(question)
        ):
            raise AppError(409, "question_duplicate", "题库中已有完全相同的问题。")
        await repo.mark_added(db, item_id, question_id)
        added = await repo.item(db, item_id)
    return CurationItem.model_validate(dict(added))


async def question_bank(
    db: AsyncSession,
    identity: Identity,
    *,
    limit: int,
    offset: int,
) -> list[BankQuestion]:
    _administrator(identity)
    rows = await repo.bank_questions(db, limit, offset)
    return [BankQuestion.model_validate(dict(row)) for row in rows]
