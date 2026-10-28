"""Persistence operations for the preparing slice.

All functions use the caller's AsyncSession so service code owns transaction scope.
"""

from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def create_session(db: AsyncSession, session_id: UUID, user_id: UUID) -> None:
    await db.execute(
        text("INSERT INTO app.interview_sessions (id, user_id) VALUES (:id, :user_id)"),
        {"id": session_id, "user_id": user_id},
    )


async def get_session(
    db: AsyncSession, session_id: UUID, user_id: UUID, *, lock: bool = False
) -> Mapping | None:
    result = await db.execute(
        text(
            """
            SELECT s.id, s.status, s.interview_direction, s.selected_sections,
                   s.termination_reason, s.curation_review, s.created_at, s.updated_at,
                   s.completed_at,
                   EXISTS (SELECT 1 FROM app.session_snapshots sn WHERE sn.session_id = s.id)
                       AS has_snapshot,
                   EXISTS (SELECT 1 FROM app.interview_plans p WHERE p.session_id = s.id)
                       AS has_plan
            FROM app.interview_sessions s
            WHERE s.id = :id AND s.user_id = :user_id
        """
            + (" FOR UPDATE OF s" if lock else "")
        ),
        {"id": session_id, "user_id": user_id},
    )
    return result.mappings().one_or_none()


async def list_sessions(db: AsyncSession, user_id: UUID, limit: int, offset: int) -> list[Mapping]:
    result = await db.execute(
        text("""
            SELECT id, status, interview_direction, termination_reason, created_at, updated_at
            FROM app.interview_sessions
            WHERE user_id = :user_id
            ORDER BY updated_at DESC, id DESC
            LIMIT :limit OFFSET :offset
        """),
        {"user_id": user_id, "limit": limit, "offset": offset},
    )
    return list(result.mappings().all())


async def get_snapshot(db: AsyncSession, session_id: UUID) -> str | None:
    result = await db.execute(
        text("SELECT content FROM app.session_snapshots WHERE session_id = :id"),
        {"id": session_id},
    )
    return result.scalar_one_or_none()


async def get_plan(db: AsyncSession, session_id: UUID) -> dict | None:
    result = await db.execute(
        text("SELECT plan FROM app.interview_plans WHERE session_id = :id"), {"id": session_id}
    )
    return result.scalar_one_or_none()


async def save_plan(db: AsyncSession, session_id: UUID, plan_json: str) -> None:
    await db.execute(
        text("""
            INSERT INTO app.interview_plans (session_id, plan)
            VALUES (:id, CAST(:plan AS jsonb))
        """),
        {"id": session_id, "plan": plan_json},
    )


async def replace_snapshot(db: AsyncSession, session_id: UUID, content: str) -> None:
    await db.execute(
        text("""
            INSERT INTO app.session_snapshots (session_id, content)
            VALUES (:id, :content)
            ON CONFLICT (session_id) DO UPDATE
            SET content = EXCLUDED.content, updated_at = now()
        """),
        {"id": session_id, "content": content},
    )


async def set_source_handle(db: AsyncSession, session_id: UUID, source_handle: str) -> None:
    await db.execute(
        text("""
            UPDATE app.interview_sessions SET source_handle = :handle, updated_at = now()
            WHERE id = :id
        """),
        {"id": session_id, "handle": source_handle},
    )


async def clear_selection_and_plan(db: AsyncSession, session_id: UUID) -> None:
    await db.execute(
        text("""
            UPDATE app.interview_sessions
            SET selected_sections = '[]'::jsonb, updated_at = now()
            WHERE id = :id
        """),
        {"id": session_id},
    )
    await db.execute(
        text("DELETE FROM app.interview_plans WHERE session_id = :id"), {"id": session_id}
    )


async def save_selection(
    db: AsyncSession, session_id: UUID, direction: str, sections_json: str
) -> None:
    await db.execute(
        text("""
            UPDATE app.interview_sessions
            SET interview_direction = :direction,
                selected_sections = CAST(:sections AS jsonb), updated_at = now()
            WHERE id = :id
        """),
        {"id": session_id, "direction": direction, "sections": sections_json},
    )
    await db.execute(
        text("DELETE FROM app.interview_plans WHERE session_id = :id"), {"id": session_id}
    )


async def get_append_receipt(db: AsyncSession, operation_key: str) -> Mapping | None:
    result = await db.execute(
        text("""
            SELECT session_id, payload_hash FROM app.snapshot_append_operations
            WHERE operation_key = :key
        """),
        {"key": operation_key},
    )
    return result.mappings().one_or_none()


async def insert_append_receipt(
    db: AsyncSession, operation_key: str, session_id: UUID, payload_hash: str
) -> None:
    await db.execute(
        text("""
            INSERT INTO app.snapshot_append_operations
                (operation_key, session_id, section, payload_hash)
            VALUES (:key, :id, '用户意见', :hash)
        """),
        {"key": operation_key, "id": session_id, "hash": payload_hash},
    )
