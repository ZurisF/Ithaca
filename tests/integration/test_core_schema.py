"""Gate 1 invariants that must be rejected by PostgreSQL itself."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import engine

USER_ID = "00000000-0000-4000-8000-000000000001"


@pytest.mark.asyncio
async def test_session_status_and_turn_constraints() -> None:
    session_id = uuid4()
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(
                text("INSERT INTO app.interview_sessions (id, user_id) VALUES (:id, :user_id)"),
                {"id": session_id, "user_id": USER_ID},
            )
            with pytest.raises(DBAPIError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("""
                            UPDATE app.interview_sessions
                            SET status = 'completed', termination_reason = NULL
                            WHERE id = :id
                        """),
                        {"id": session_id},
                    )
            await connection.execute(
                text("""
                    INSERT INTO app.turns (session_id, turn_no, stage_index, question)
                    VALUES (:id, 1, 0, '为什么选择这个方案？')
                """),
                {"id": session_id},
            )
            with pytest.raises(DBAPIError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("""
                            INSERT INTO app.turns (session_id, turn_no, stage_index, question)
                            VALUES (:id, 2, 0, '第二道未回答的问题？')
                        """),
                        {"id": session_id},
                    )
            with pytest.raises(DBAPIError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("""
                            INSERT INTO app.turns (session_id, turn_no, stage_index, question, answer)
                            VALUES (:id, 2, 0, '问题？', '回答')
                        """),
                        {"id": session_id},
                    )
            with pytest.raises(DBAPIError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("""
                            INSERT INTO app.turns (session_id, turn_no, stage_index, question,
                                                   answer, answered_at)
                            VALUES (:id, 101, 0, '问题？', '回答', now())
                        """),
                        {"id": session_id},
                    )
        finally:
            await transaction.rollback()
