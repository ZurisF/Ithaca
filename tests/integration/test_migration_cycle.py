"""Opt-in empty-database upgrade, downgrade and upgrade verification."""

import asyncio
import os
import re
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from app.settings import get_settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(
    os.getenv("RUN_MIGRATION_CYCLE") != "1", reason="requires CREATE DATABASE privilege"
)
@pytest.mark.asyncio
async def test_migrations_upgrade_downgrade_and_upgrade_on_empty_database() -> None:
    base = make_url(get_settings().database_url)
    name = f"ithaca_gate1_{uuid4().hex[:12]}"
    assert re.fullmatch(r"ithaca_gate1_[0-9a-f]{12}", name)
    admin = await asyncpg.connect(
        host=base.host,
        port=base.port or 5432,
        user=base.username,
        password=base.password,
        database="postgres",
    )
    await admin.execute(f'CREATE DATABASE "{name}"')
    url = base.set(database=name).render_as_string(hide_password=False)
    env = {**os.environ, "APP_DATABASE_URL": url}

    async def migrate(action: str, target: str) -> None:
        process = await asyncio.create_subprocess_exec(
            str(Path(sys.executable).with_name("alembic")),
            "-c",
            "services/application/alembic.ini",
            action,
            target,
            cwd=ROOT,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()
        assert process.returncode == 0, f"alembic {action} {target} failed"

    try:
        await migrate("upgrade", "head")
        connection = await asyncpg.connect(
            host=base.host,
            port=base.port or 5432,
            user=base.username,
            password=base.password,
            database=name,
        )
        try:
            assert await connection.fetchval("SELECT to_regclass('app.interview_sessions')")
            assert await connection.fetchval("SELECT to_regclass('app.post_tasks')")
            assert await connection.fetchval("SELECT to_regclass('bank.questions')")
            assert await connection.fetchval("SELECT to_regclass('telemetry.model_calls')")
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM pg_indexes WHERE schemaname = 'app' "
                    "AND indexname = 'post_tasks_natural'"
                )
                == 1
            )
        finally:
            await connection.close()
        await migrate("downgrade", "base")
        await migrate("upgrade", "head")
    finally:
        await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        await admin.close()
