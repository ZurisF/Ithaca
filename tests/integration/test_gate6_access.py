"""Gate 6 user resource access stays owner-scoped across views and exports."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from test_gate4_interview import HEADERS, Harness, ScriptedModel

from app.db import engine


@pytest.mark.asyncio
async def test_non_owner_cannot_read_interview_result_exports_or_events():
    other_user = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO app.users (id, role, display_name) VALUES (:id, 'user', 'Other user')"
            ),
            {"id": other_user},
        )
    try:
        async with Harness(ScriptedModel()) as harness:
            _, base, started = await harness.create()
            assert started["awaiting"] == "answer"
            for suffix in (
                "/current",
                "/full-qa",
                "/full-qa.md",
                "/report",
                "/report.md",
                "/snapshot.md",
                "/events",
            ):
                denied = await harness.client.get(
                    f"{base}{suffix}", headers={"X-Dev-User": str(other_user)}
                )
                assert denied.status_code == 404, (suffix, denied.text)
            owned = await harness.client.get(f"{base}/full-qa", headers=HEADERS)
            assert owned.status_code == 200
            assert len(owned.json()["turns"]) == 1
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM app.users WHERE id = :id"), {"id": other_user}
            )
