"""Finalization facts. Callers own short transactions and lock the session first."""

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _task_key(session_id: UUID, kind: str, turn_no: int | None) -> str:
    return f"{session_id}:{kind}" + (f":{turn_no}" if turn_no is not None else "")


async def locked_session(db: AsyncSession, session_id: UUID) -> Mapping | None:
    result = await db.execute(
        text("""
        SELECT status, feedback_frozen_at FROM app.interview_sessions
        WHERE id = :id FOR UPDATE
    """),
        {"id": session_id},
    )
    return result.mappings().one_or_none()


async def put_feedback(
    db: AsyncSession, session_id: UUID, turn_no: int, value: str, reason: str | None
) -> None:
    await db.execute(
        text("""
        INSERT INTO app.question_feedback (session_id, turn_no, value, reason)
        VALUES (:id, :turn_no, :value, :reason)
        ON CONFLICT (session_id, turn_no) DO UPDATE
        SET value = EXCLUDED.value, reason = EXCLUDED.reason, updated_at = now()
    """),
        {"id": session_id, "turn_no": turn_no, "value": value, "reason": reason},
    )


async def feedback_frozen_at(db: AsyncSession, session_id: UUID):
    return await db.scalar(
        text("SELECT feedback_frozen_at FROM app.interview_sessions WHERE id = :id"),
        {"id": session_id},
    )


async def turns(db: AsyncSession, session_id: UUID) -> list[Mapping]:
    result = await db.execute(
        text("""
        SELECT t.turn_no, t.stage_index, t.question, t.answer, t.interviewer_message,
               t.question_id, r.project_answer, r.ideal_answer, r.comment,
               f.value AS feedback_value, f.reason AS feedback_reason
        FROM app.turns t
        LEFT JOIN app.turn_post_results r USING (session_id, turn_no)
        LEFT JOIN app.question_feedback f USING (session_id, turn_no)
        WHERE t.session_id = :id ORDER BY t.turn_no
    """),
        {"id": session_id},
    )
    return list(result.mappings().all())


async def settle(db: AsyncSession, session_id: UUID) -> bool:
    inserted = await db.execute(
        text("""
        INSERT INTO bank.session_settlements (session_id) VALUES (:id)
        ON CONFLICT DO NOTHING RETURNING session_id
    """),
        {"id": session_id},
    )
    if inserted.scalar_one_or_none() is None:
        return False
    await db.execute(
        text("""
        WITH counts AS (
            SELECT t.question_id,
                   count(*) AS usage,
                   count(*) FILTER (WHERE f.value = 'upvote') AS upvotes,
                   count(*) FILTER (WHERE f.value = 'downvote') AS downvotes
            FROM app.turns t
            LEFT JOIN app.question_feedback f USING (session_id, turn_no)
            WHERE t.session_id = :id AND t.question_id IS NOT NULL
            GROUP BY t.question_id
        )
        UPDATE bank.questions q SET
            usage_count = q.usage_count + counts.usage,
            upvote_count = q.upvote_count + counts.upvotes,
            downvote_count = q.downvote_count + counts.downvotes,
            updated_at = now()
        FROM counts WHERE q.id = counts.question_id
    """),
        {"id": session_id},
    )
    return True


async def has_published_artifacts(db: AsyncSession, session_id: UUID) -> bool:
    result = await db.execute(
        text("""
        SELECT EXISTS (SELECT 1 FROM app.turn_post_results WHERE session_id = :id)
            OR EXISTS (SELECT 1 FROM app.session_reports WHERE session_id = :id)
            OR EXISTS (SELECT 1 FROM app.snapshot_append_operations
                       WHERE session_id = :id AND section = '事后核验')
    """),
        {"id": session_id},
    )
    return bool(result.scalar_one())


async def cancel_tasks(db: AsyncSession, session_id: UUID) -> None:
    await db.execute(text("DELETE FROM app.post_tasks WHERE session_id = :id"), {"id": session_id})


async def claim_task(
    db: AsyncSession, session_id: UUID, kind: str, turn_no: int | None, owner: str
) -> bool:
    key = _task_key(session_id, kind, turn_no)
    await db.execute(
        text("""
        INSERT INTO app.post_tasks (task_key, session_id, kind, turn_no, status)
        VALUES (:key, :id, :kind, :turn_no, 'pending') ON CONFLICT DO NOTHING
    """),
        {"key": key, "id": session_id, "kind": kind, "turn_no": turn_no},
    )
    # Exhausted expired leases must become terminal; otherwise they stay running forever.
    await db.execute(
        text("""
        UPDATE app.post_tasks SET status = 'failed', last_error_code = 'lease_expired',
            lease_owner = NULL, lease_expires_at = NULL, finished_at = now(), updated_at = now()
        WHERE task_key = :key AND status = 'running' AND lease_expires_at < now()
          AND attempt_count >= 3
    """),
        {"key": key},
    )
    result = await db.execute(
        # Claim count bounds crash recovery; each model call has its own adapter retry budget.
        text("""
        UPDATE app.post_tasks SET status = 'running', attempt_count = attempt_count + 1,
            lease_owner = :owner, lease_expires_at = now() + interval '20 minutes',
            started_at = COALESCE(started_at, now()), updated_at = now()
        WHERE task_key = :key AND attempt_count < 3
          AND (status = 'pending' OR (status = 'running' AND lease_expires_at < now()))
        RETURNING task_key
    """),
        {"key": key, "owner": owner},
    )
    return result.scalar_one_or_none() is not None


async def task_status(
    db: AsyncSession, session_id: UUID, kind: str, turn_no: int | None
) -> str | None:
    key = _task_key(session_id, kind, turn_no)
    result = await db.execute(
        text("SELECT status FROM app.post_tasks WHERE task_key = :key"), {"key": key}
    )
    return result.scalar_one_or_none()


async def finish_task(
    db: AsyncSession,
    session_id: UUID,
    kind: str,
    turn_no: int | None,
    owner: str,
    *,
    error: str | None = None,
) -> bool:
    key = _task_key(session_id, kind, turn_no)
    result = await db.execute(
        text("""
        UPDATE app.post_tasks SET status = :status, last_error_code = :error,
            lease_owner = NULL, lease_expires_at = NULL,
            finished_at = now(), updated_at = now()
        WHERE task_key = :key AND status = 'running' AND lease_owner = :owner
          AND lease_expires_at > now() RETURNING task_key
    """),
        {"key": key, "owner": owner, "status": "failed" if error else "succeeded", "error": error},
    )
    return result.scalar_one_or_none() is not None


async def active_lease(
    db: AsyncSession, session_id: UUID, kind: str, turn_no: int | None, owner: str
) -> bool:
    result = await db.execute(
        text("""
        SELECT 1 FROM app.post_tasks WHERE task_key = :key AND status = 'running'
          AND lease_owner = :owner AND lease_expires_at > now() FOR UPDATE
    """),
        {"key": _task_key(session_id, kind, turn_no), "owner": owner},
    )
    return result.scalar_one_or_none() is not None


async def write_turn_result(
    db: AsyncSession, session_id: UUID, turn_no: int, column: str, value: str
) -> None:
    if column not in {"project_answer", "ideal_answer", "comment"}:
        raise ValueError("invalid result column")
    await db.execute(
        text(f"""
        INSERT INTO app.turn_post_results (session_id, turn_no, {column})
        VALUES (:id, :turn_no, :value)
        ON CONFLICT (session_id, turn_no) DO UPDATE
        SET {column} = EXCLUDED.{column}, updated_at = now()
    """),
        {"id": session_id, "turn_no": turn_no, "value": value},
    )


async def write_report(db: AsyncSession, session_id: UUID, report_json: str) -> None:
    await db.execute(
        text("""
        INSERT INTO app.session_reports (session_id, report)
        VALUES (:id, CAST(:report AS jsonb)) ON CONFLICT DO NOTHING
    """),
        {"id": session_id, "report": report_json},
    )


async def get_report(db: AsyncSession, session_id: UUID) -> dict | None:
    result = await db.execute(
        text("SELECT report FROM app.session_reports WHERE session_id = :id"), {"id": session_id}
    )
    return result.scalar_one_or_none()


async def ideal_from_bank(db: AsyncSession, question_id: UUID | None) -> str | None:
    if question_id is None:
        return None
    result = await db.execute(
        text("SELECT ideal_answer FROM bank.questions WHERE id = :id"), {"id": question_id}
    )
    return result.scalar_one_or_none()


async def worker_candidates(db: AsyncSession, limit: int = 20) -> list[Mapping]:
    result = await db.execute(
        text("""
        SELECT s.id, s.user_id, s.status FROM app.interview_sessions s
        WHERE s.status = 'post_processing'
           OR (s.status IN ('completed', 'aborted') AND NOT EXISTS
               (SELECT 1 FROM bank.session_settlements b WHERE b.session_id = s.id))
        ORDER BY s.updated_at, s.id LIMIT :limit FOR UPDATE OF s SKIP LOCKED
    """),
        {"limit": limit},
    )
    return list(result.mappings().all())
