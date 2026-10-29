"""PostgreSQL facts and conditional writes for the live interview."""

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def latest_turn(db: AsyncSession, session_id: UUID) -> Mapping | None:
    result = await db.execute(
        text("""
        SELECT turn_no, stage_index, question, answer, interviewer_message,
               question_shown_at, answered_at
        FROM app.turns WHERE session_id = :session_id
        ORDER BY turn_no DESC LIMIT 1
    """),
        {"session_id": session_id},
    )
    return result.mappings().one_or_none()


async def get_turn(db: AsyncSession, session_id: UUID, turn_no: int) -> Mapping | None:
    result = await db.execute(
        text("""
        SELECT turn_no, stage_index, question, answer, interviewer_message,
               question_shown_at, answered_at
        FROM app.turns WHERE session_id = :session_id AND turn_no = :turn_no
        """),
        {"session_id": session_id, "turn_no": turn_no},
    )
    return result.mappings().one_or_none()


async def turns_for_context(db: AsyncSession, session_id: UUID) -> list[Mapping]:
    result = await db.execute(
        text("""
        SELECT turn_no, stage_index, question, answer, interviewer_message
        FROM app.turns WHERE session_id = :session_id
        ORDER BY turn_no
        """),
        {"session_id": session_id},
    )
    return list(result.mappings().all())


async def stage_results(db: AsyncSession, session_id: UUID) -> list[Mapping]:
    result = await db.execute(
        text("""
        SELECT stage_index, stage_id, result FROM app.stage_results
        WHERE session_id = :session_id ORDER BY stage_index
        """),
        {"session_id": session_id},
    )
    return list(result.mappings().all())


async def first_open_stage(db: AsyncSession, session_id: UUID, stage_count: int) -> int | None:
    result = await db.execute(
        text("""
        SELECT stage_index FROM app.stage_results WHERE session_id = :session_id
    """),
        {"session_id": session_id},
    )
    closed = {row[0] for row in result}
    return next((index for index in range(stage_count) if index not in closed), None)


async def enter_interview(db: AsyncSession, session_id: UUID) -> None:
    await db.execute(
        text("""
        UPDATE app.interview_sessions SET status = 'interviewing', updated_at = now()
        WHERE id = :session_id AND status = 'preparing'
    """),
        {"session_id": session_id},
    )


async def answer_current_turn(
    db: AsyncSession, session_id: UUID, turn_no: int, answer: str
) -> bool:
    result = await db.execute(
        text("""
        UPDATE app.turns SET answer = :answer, answered_at = now()
        WHERE session_id = :session_id AND turn_no = :turn_no AND answer IS NULL
        AND NOT EXISTS (
            SELECT 1 FROM app.turns newer
            WHERE newer.session_id = :session_id AND newer.turn_no > :turn_no
        )
        RETURNING turn_no
        """),
        {"session_id": session_id, "turn_no": turn_no, "answer": answer},
    )
    return result.scalar_one_or_none() is not None


async def publish_next_turn(
    db: AsyncSession,
    session_id: UUID,
    turn_no: int,
    stage_index: int,
    question: str,
    question_id: UUID | None,
    *,
    answered_turn_no: int | None,
    interviewer_message: str | None,
) -> bool:
    result = await db.execute(
        text("""
        INSERT INTO app.turns (session_id, turn_no, stage_index, question, question_id)
        VALUES (:session_id, :turn_no, :stage_index, :question, :question_id)
        ON CONFLICT (session_id, turn_no) DO NOTHING RETURNING turn_no
        """),
        {
            "session_id": session_id,
            "turn_no": turn_no,
            "stage_index": stage_index,
            "question": question,
            "question_id": question_id,
        },
    )
    if result.scalar_one_or_none() is None:
        return False
    if answered_turn_no is not None:
        await db.execute(
            text("""
            UPDATE app.turns SET interviewer_message = :message
            WHERE session_id = :session_id AND turn_no = :turn_no
            """),
            {"session_id": session_id, "turn_no": answered_turn_no, "message": interviewer_message},
        )
    return True


async def close_stage(
    db: AsyncSession,
    session_id: UUID,
    stage_index: int,
    stage_id: str,
    result_value: str,
    answered_turn_no: int,
    interviewer_message: str | None,
) -> bool:
    result = await db.execute(
        text("""
        INSERT INTO app.stage_results (session_id, stage_index, stage_id, result)
        VALUES (:session_id, :stage_index, :stage_id, :result)
        ON CONFLICT (session_id, stage_index) DO NOTHING RETURNING stage_index
        """),
        {
            "session_id": session_id,
            "stage_index": stage_index,
            "stage_id": stage_id,
            "result": result_value,
        },
    )
    if result.scalar_one_or_none() is None:
        return False
    await db.execute(
        text("""
        UPDATE app.turns SET interviewer_message = :message
        WHERE session_id = :session_id AND turn_no = :turn_no
        """),
        {"session_id": session_id, "turn_no": answered_turn_no, "message": interviewer_message},
    )
    return True


async def terminate_interview(db: AsyncSession, session_id: UUID, reason: str, post: bool) -> None:
    await db.execute(
        text("""
        UPDATE app.interview_sessions
        SET status = :status, termination_reason = :reason,
            feedback_frozen_at = COALESCE(feedback_frozen_at, now()),
            completed_at = CASE WHEN :post THEN completed_at ELSE now() END,
            updated_at = now()
        WHERE id = :session_id AND status = 'interviewing'
        """),
        {
            "session_id": session_id,
            "reason": reason,
            "status": "post_processing" if post else "completed",
            "post": post,
        },
    )


async def recoverable_sessions(db: AsyncSession, limit: int = 20) -> list[Mapping]:
    result = await db.execute(
        text("""
        SELECT s.id, s.user_id FROM app.interview_sessions s
        WHERE s.status = 'interviewing'
          AND NOT EXISTS (
            SELECT 1 FROM app.turns t
            WHERE t.session_id = s.id AND t.answer IS NULL
          )
        ORDER BY s.updated_at, s.id
        LIMIT :limit FOR UPDATE OF s SKIP LOCKED
        """),
        {"limit": limit},
    )
    return list(result.mappings().all())
