"""Public directory choice keeps the real path inside Local Runtime."""

from pathlib import Path
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text

from app.db import engine
from app.main import app
from app.services import prepare as prepare_service
from local_project.api import sources as local_sources
from local_project.main import app as local_app
from local_project.source_registry.registry import registry

USER_ID = "00000000-0000-4000-8000-000000000001"


@pytest.mark.asyncio
async def test_public_source_choice_shows_only_safe_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("# Project\nA safe description.\n", encoding="utf-8")
    (root / "config.py").write_text("api_key = 'sk-123456789012345678901234'\n", encoding="utf-8")

    async def fake_chooser() -> str:
        return str(root)

    monkeypatch.setattr(local_sources, "choose_directory", fake_chooser)
    original_client = httpx.AsyncClient

    def local_client(**kwargs) -> httpx.AsyncClient:
        return original_client(
            transport=httpx.ASGITransport(app=local_app), base_url="http://local", **kwargs
        )

    application = original_client(transport=httpx.ASGITransport(app=app), base_url="http://app")
    monkeypatch.setattr(prepare_service.httpx, "AsyncClient", local_client)
    session_id = None
    handle = None
    async with application:
        try:
            created = await application.post("/v1/interviews", headers={"X-Dev-User": USER_ID})
            assert created.status_code == 201, created.text
            session_id = created.json()["id"]
            path = f"/v1/interviews/{session_id}"
            chosen = await application.post(
                f"{path}/source:choose", headers={"X-Dev-User": USER_ID}
            )
            assert chosen.status_code == 200, chosen.text
            handle = chosen.json()["source_handle"]
            assert str(root) not in chosen.text
            assert "sk-123456789012345678901234" not in chosen.text
            config = next(
                item for item in chosen.json()["files"] if item["relative_path"] == "config.py"
            )
            assert config["redactions"] == [{"kind": "credential_assignment", "line": 1}]
            current = await application.get(path, headers={"X-Dev-User": USER_ID})
            assert current.status_code == 200
            assert current.json()["source_handle"] == handle
            assert str(root) not in current.text
            inventory = await application.get(
                f"{path}/source/inventory", headers={"X-Dev-User": USER_ID}
            )
            assert inventory.status_code == 200
            assert inventory.json() == chosen.json()
        finally:
            if handle and session_id:
                registry.release(handle, UUID(session_id))
            if session_id:
                async with engine.begin() as connection:
                    await connection.execute(
                        text("DELETE FROM app.interview_sessions WHERE id = :id"),
                        {"id": session_id},
                    )
