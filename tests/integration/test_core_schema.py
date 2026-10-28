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


@pytest.mark.asyncio
async def test_natural_keys_and_opaque_source_handle_are_database_constraints() -> None:
    session_id = uuid4()
    append_key = str(uuid4())
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
                        text(
                            "UPDATE app.interview_sessions SET source_handle = :path WHERE id = :id"
                        ),
                        {"id": session_id, "path": "/private/project/path"},
                    )
            await connection.execute(
                text("""
                    INSERT INTO app.post_tasks (task_key, session_id, kind, status)
                    VALUES ('first', :id, 'project_answers', 'pending')
                """),
                {"id": session_id},
            )
            with pytest.raises(DBAPIError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("""
                            INSERT INTO app.post_tasks (task_key, session_id, kind, status)
                            VALUES ('second', :id, 'project_answers', 'pending')
                        """),
                        {"id": session_id},
                    )
            await connection.execute(
                text("""
                    INSERT INTO app.snapshot_append_operations
                        (operation_key, session_id, section, payload_hash)
                    VALUES (:key, :id, '用户意见', 'hash-a')
                """),
                {"key": append_key, "id": session_id},
            )
            with pytest.raises(DBAPIError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("""
                            INSERT INTO app.snapshot_append_operations
                                (operation_key, session_id, section, payload_hash)
                            VALUES (:key, :id, '用户意见', 'hash-b')
                        """),
                        {"key": append_key, "id": session_id},
                    )
            await connection.execute(
                text("""
                    INSERT INTO app.stage_results
                        (session_id, stage_index, stage_id, result)
                    VALUES (:id, 0, 'stage-a', 'complete')
                """),
                {"id": session_id},
            )
            with pytest.raises(DBAPIError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("""
                            INSERT INTO app.stage_results
                                (session_id, stage_index, stage_id, result)
                            VALUES (:id, 1, 'stage-a', 'unresolved')
                        """),
                        {"id": session_id},
                    )
            await connection.execute(
                text("INSERT INTO bank.session_settlements (session_id) VALUES (:id)"),
                {"id": session_id},
            )
            with pytest.raises(DBAPIError):
                async with connection.begin_nested():
                    await connection.execute(
                        text("INSERT INTO bank.session_settlements (session_id) VALUES (:id)"),
                        {"id": session_id},
                    )
        finally:
            await transaction.rollback()
