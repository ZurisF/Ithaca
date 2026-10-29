"""Session ownership and preparing-state checks shared by preparation commands."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.access import Identity
from app.repositories import prepare as repo
from app.services.errors import AppError


def require_user(identity: Identity) -> None:
    if identity.role != "user":
        raise AppError(403, "forbidden", "只有 User 可以创建和管理面试会话。")


def require_preparing(row) -> None:
    if row["status"] != "preparing":
        raise AppError(409, "state_conflict", "当前会话已离开准备阶段。")


async def owned_session(db: AsyncSession, session_id: UUID, identity: Identity, *, lock: bool):
    require_user(identity)
    row = await repo.get_session(db, session_id, identity.id, lock=lock)
    if row is None:
        raise AppError(404, "session_not_found", "找不到这场面试。")
    return row
