"""Run with RUN_CROSS_RUNTIME=1 while both Runtime processes are listening on loopback."""

import os
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from app.db import engine
from app.settings import get_settings as get_app_settings
from local_project.settings import get_settings as get_local_settings

USER_ID = "00000000-0000-4000-8000-000000000001"


@pytest.mark.skipif(
    os.getenv("RUN_CROSS_RUNTIME") != "1", reason="requires two live Runtime processes"
)
@pytest.mark.asyncio
async def test_source_handle_is_bound_across_processes(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text(
        "# 项目\n## Threads\n### Request Flow\n证据。\n", encoding="utf-8"
    )
    app_settings = get_app_settings()
    local_settings = get_local_settings()
    assert app_settings.desktop_instance_token == local_settings.desktop_instance_token

    session_ids: list[str] = []
    handle = None
    async with (
        httpx.AsyncClient(
            base_url="http://127.0.0.1:8100", timeout=10, trust_env=False
        ) as application,
        httpx.AsyncClient(base_url="http://127.0.0.1:8101", timeout=10, trust_env=False) as local,
    ):
        headers = {"X-Dev-User": USER_ID}
        local_headers = {"Authorization": f"Bearer {local_settings.desktop_instance_token}"}
        try:
            for _ in range(2):
                created = await application.post("/v1/interviews", headers=headers)
                assert created.status_code == 201, created.text
                session_ids.append(created.json()["id"])
            authorized = await local.post(
                "/v1/sources:authorize",
                headers=local_headers,
                json={"session_id": session_ids[0], "path": str(root)},
            )
            assert authorized.status_code == 200, authorized.text
            handle = authorized.json()["source_handle"]
            markdown = "# Demo\n## Threads\n### Request Flow\n说明。\n"
            wrong = await application.post(
                f"/v1/interviews/{session_ids[1]}/snapshot:import",
                headers=headers,
                json={"markdown": markdown, "source_handle": handle},
            )
            assert wrong.status_code == 403
            valid = await application.post(
                f"/v1/interviews/{session_ids[0]}/snapshot:import",
                headers=headers,
                json={"markdown": markdown, "source_handle": handle},
            )
            assert valid.status_code == 200, valid.text
            assert str(root) not in valid.text
        finally:
            if handle:
                await local.delete(
                    f"/v1/sources/{handle}",
                    headers=local_headers,
                    params={"session_id": session_ids[0]},
                )
            async with engine.begin() as connection:
                for session_id in session_ids:
                    await connection.execute(
                        text("DELETE FROM app.interview_sessions WHERE id = :id"),
                        {"id": session_id},
                    )
