"""PostgreSQL facts for the interview entry boundary."""

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


async def publish_first_turn(
    db: AsyncSession, session_id: UUID, question: str, question_id: UUID | None
) -> bool:
    result = await db.execute(
        text("""
        INSERT INTO app.turns (session_id, turn_no, stage_index, question, question_id)
        SELECT :session_id, 1, 0, :question, :question_id
        WHERE EXISTS (
            SELECT 1 FROM app.interview_sessions
            WHERE id = :session_id AND status = 'interviewing'
        )
        AND NOT EXISTS (SELECT 1 FROM app.turns WHERE session_id = :session_id)
        AND NOT EXISTS (SELECT 1 FROM app.stage_results WHERE session_id = :session_id)
        ON CONFLICT (session_id, turn_no) DO NOTHING
        RETURNING turn_no
    """),
        {
            "session_id": session_id,
            "question": question,
            "question_id": question_id,
        },
    )
    return result.scalar_one_or_none() is not None
