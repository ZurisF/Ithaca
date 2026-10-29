"""Owner-scoped session deletion with ordered checkpoint and local-handle cleanup."""

import logging
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access import Identity
from app.services.errors import AppError
from app.services.interview_checkpoint import delete_checkpoint, execution_lock
from app.services.prepare import _release_source
from app.services.session_access import owned_session

logger = logging.getLogger(__name__)


async def delete(db: AsyncSession, identity: Identity, session_id: UUID) -> None:
    async with execution_lock(session_id):
        async with db.begin():
            row = await owned_session(db, session_id, identity, lock=True)
            handle = row["source_handle"]
        try:
            await delete_checkpoint(session_id)
        except Exception as exc:
            raise AppError(
                503, "cleanup_failed", "会话执行现场清理失败，请重试删除。", True
            ) from exc
        async with db.begin():
            await owned_session(db, session_id, identity, lock=True)
            await db.execute(
                text("DELETE FROM app.interview_sessions WHERE id = :id"), {"id": session_id}
            )
        if handle:
            await _release_source(session_id, handle)
        try:
            await delete_checkpoint(session_id)
        except Exception:  # noqa: BLE001 - Redis TTL removes any late checkpoint
            logger.warning("deleted_session_checkpoint_second_cleanup_failed")
