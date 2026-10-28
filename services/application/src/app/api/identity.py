from dataclasses import dataclass
from uuid import UUID

from fastapi import Header
from sqlalchemy import text

from app.api.errors import AppError
from app.db import session_factory
from app.settings import get_settings


@dataclass(frozen=True)
class Identity:
    id: UUID
    role: str
    display_name: str | None


async def get_identity(
    x_dev_user: str | None = Header(default=None),
) -> Identity:
    # Development-only resolver. Deployment must replace it with a verified identity provider.
    if not get_settings().dev_auth_enabled or not x_dev_user:
        raise AppError(401, "unauthenticated", "需要登录。")
    try:
        user_id = UUID(x_dev_user)
    except ValueError as exc:
        raise AppError(401, "unauthenticated", "开发身份无效。") from exc
    async with session_factory() as db:
        result = await db.execute(
            text("SELECT id, role, display_name FROM app.users WHERE id = :id"), {"id": user_id}
        )
        row = result.mappings().one_or_none()
    if row is None:
        raise AppError(401, "unauthenticated", "开发身份无效。")
    return Identity(id=row["id"], role=row["role"], display_name=row["display_name"])
