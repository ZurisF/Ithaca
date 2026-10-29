"""Curation and public bank persistence; transactions belong to the service."""

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def source(db: AsyncSession, session_id: UUID, *, lock: bool = False) -> Mapping | None:
    result = await db.execute(
        text(
            """
            SELECT id, status, curation_review
            FROM app.interview_sessions
            WHERE id = :id AND curation_review = true
              AND status IN ('completed', 'aborted')
        """
            + (" FOR UPDATE" if lock else "")
        ),
        {"id": session_id},
    )
    return result.mappings().one_or_none()


async def authorized_sources(db: AsyncSession, limit: int, offset: int) -> list[Mapping]:
    result = await db.execute(
        text("""
            SELECT id AS session_id, status, updated_at
            FROM app.interview_sessions
            WHERE curation_review = true AND status IN ('completed', 'aborted')
            ORDER BY updated_at DESC, id DESC LIMIT :limit OFFSET :offset
        """),
        {"limit": limit, "offset": offset},
    )
    return list(result.mappings())


async def source_turns(db: AsyncSession, session_ids: list[UUID]) -> list[Mapping]:
    result = await db.execute(
        text("""
            SELECT t.session_id, t.turn_no, t.question, t.answer,
                   f.value AS feedback_value, f.reason AS feedback_reason
            FROM app.turns t
            JOIN app.interview_sessions s ON s.id = t.session_id
              AND s.curation_review = true AND s.status IN ('completed', 'aborted')
            LEFT JOIN app.question_feedback f USING (session_id, turn_no)
            WHERE t.session_id = ANY(CAST(:ids AS uuid[]))
            ORDER BY t.session_id, t.turn_no
        """),
        {"ids": session_ids},
    )
    return list(result.mappings())


async def items(db: AsyncSession, session_ids: list[UUID]) -> list[Mapping]:
    result = await db.execute(
        text("""
            SELECT i.id, i.source_session_id, i.source_turn_no, i.status,
                   i.edited_question, i.proposed_topic_path, i.review_notes,
                   i.reviewed_by, i.question_bank_id,
                   EXISTS (SELECT 1 FROM bank.questions q
                           WHERE q.question = i.edited_question) AS exact_duplicate
            FROM app.curation_items i
            JOIN app.interview_sessions s ON s.id = i.source_session_id
              AND s.curation_review = true AND s.status IN ('completed', 'aborted')
            WHERE i.source_session_id = ANY(CAST(:ids AS uuid[]))
            ORDER BY i.created_at DESC, i.id DESC
        """),
        {"ids": session_ids},
    )
    return list(result.mappings())


async def item(db: AsyncSession, item_id: UUID) -> Mapping | None:
    result = await db.execute(
        text("""
            SELECT i.id, i.source_session_id, i.source_turn_no, i.status,
                   i.edited_question, i.proposed_topic_path, i.review_notes,
                   i.reviewed_by, i.question_bank_id,
                   EXISTS (SELECT 1 FROM bank.questions q
                           WHERE q.question = i.edited_question) AS exact_duplicate
            FROM app.curation_items i
            JOIN app.interview_sessions s ON s.id = i.source_session_id
              AND s.curation_review = true AND s.status IN ('completed', 'aborted')
            WHERE i.id = :id
        """),
        {"id": item_id},
    )
    return result.mappings().one_or_none()


async def turn_exists(db: AsyncSession, session_id: UUID, turn_no: int) -> bool:
    return bool(
        await db.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM app.turns WHERE session_id = :id AND turn_no = :turn_no)"
            ),
            {"id": session_id, "turn_no": turn_no},
        )
    )


async def source_turn(db: AsyncSession, session_id: UUID, turn_no: int) -> Mapping | None:
    result = await db.execute(
        text("""
            SELECT t.question, t.answer, f.value AS feedback_value,
                   f.reason AS feedback_reason
            FROM app.turns t
            JOIN app.interview_sessions s ON s.id = t.session_id
              AND s.curation_review = true AND s.status IN ('completed', 'aborted')
            LEFT JOIN app.question_feedback f USING (session_id, turn_no)
            WHERE t.session_id = :id AND t.turn_no = :turn_no
        """),
        {"id": session_id, "turn_no": turn_no},
    )
    return result.mappings().one_or_none()


async def insert_item(db: AsyncSession, item_id: UUID, session_id: UUID, turn_no: int) -> None:
    await db.execute(
        text("""
            INSERT INTO app.curation_items (id, source_session_id, source_turn_no, status)
            VALUES (:id, :session_id, :turn_no, 'pending')
        """),
        {"id": item_id, "session_id": session_id, "turn_no": turn_no},
    )


async def review_item(
    db: AsyncSession,
    item_id: UUID,
    status: str,
    question: str,
    topic: str,
    notes: str,
    reviewer: UUID,
) -> None:
    await db.execute(
        text("""
            UPDATE app.curation_items SET status = :status, edited_question = :question,
                proposed_topic_path = :topic, review_notes = :notes,
                reviewed_by = :reviewer, updated_at = now()
            WHERE id = :id
        """),
        {
            "id": item_id,
            "status": status,
            "question": question,
            "topic": topic,
            "notes": notes,
            "reviewer": reviewer,
        },
    )


async def insert_question(
    db: AsyncSession,
    question_id: UUID,
    question: str,
    topic: str,
    ideal_answer: str | None,
    embedding: str,
    lexical: str,
) -> bool:
    result = await db.execute(
        text("""
            INSERT INTO bank.questions
                (id, question, topic_path, ideal_answer, embedding, lexical_document)
            VALUES (:id, :question, :topic, :answer, CAST(:embedding AS vector),
                    to_tsvector('simple', :lexical))
            ON CONFLICT (question) DO NOTHING RETURNING id
        """),
        {
            "id": question_id,
            "question": question,
            "topic": topic,
            "answer": ideal_answer,
            "embedding": embedding,
            "lexical": lexical,
        },
    )
    return result.scalar_one_or_none() is not None


async def mark_added(db: AsyncSession, item_id: UUID, question_id: UUID) -> None:
    await db.execute(
        text("""
            UPDATE app.curation_items SET status = 'added', question_bank_id = :question_id,
                updated_at = now() WHERE id = :id
        """),
        {"id": item_id, "question_id": question_id},
    )


async def bank_questions(db: AsyncSession, limit: int, offset: int) -> list[Mapping]:
    result = await db.execute(
        text("""
            SELECT id, question, topic_path, ideal_answer,
                   usage_count, upvote_count, downvote_count
            FROM bank.questions ORDER BY created_at DESC, id DESC
            LIMIT :limit OFFSET :offset
        """),
        {"limit": limit, "offset": offset},
    )
    return list(result.mappings())
