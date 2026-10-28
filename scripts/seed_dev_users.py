"""Idempotent local-only identities. Never run in a non-development deployment."""

import asyncio
from uuid import UUID

from sqlalchemy import text

from app.db import engine
from app.settings import get_settings

DEV_USER_ID = UUID("00000000-0000-4000-8000-000000000001")
DEV_ADMIN_ID = UUID("00000000-0000-4000-8000-000000000002")


async def main() -> None:
    if not get_settings().dev_auth_enabled:
        raise SystemExit("Set APP_DEV_AUTH_ENABLED=true only in local development")
    async with engine.begin() as connection:
        await connection.execute(
            text("""
                INSERT INTO app.users (id, role, display_name)
                VALUES (:user_id, 'user', 'Development User'),
                       (:admin_id, 'administrator', 'Development Administrator')
                ON CONFLICT (id) DO NOTHING
            """),
            {"user_id": DEV_USER_ID, "admin_id": DEV_ADMIN_ID},
        )
    print(f"Development User: {DEV_USER_ID}")
    print(f"Development Administrator: {DEV_ADMIN_ID}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
