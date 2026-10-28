"""Preparing slice through public HTTP; direct SQL is used only for fixture cleanup."""

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text

from app.db import engine
from app.main import app

USER_ID = "00000000-0000-4000-8000-000000000001"
ADMIN_ID = "00000000-0000-4000-8000-000000000002"
MARKDOWN = "# 项目\n## Modules\n### API\n服务入口。\n## Threads\n### Query Flow\n路径。\n"


@pytest.mark.asyncio
async def test_single_kind_and_empty_range_confirmation() -> None:
    session_id = None
    headers = {"X-Dev-User": USER_ID}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        try:
            created = await client.post("/v1/interviews", headers=headers)
            assert created.status_code == 201
            session_id = created.json()["id"]
            base = f"/v1/interviews/{session_id}"
            only_modules = "# Project\n## Modules\n### API\nEntry.\n## Notes\n### Not a range\n"
            imported = await client.post(
                f"{base}/snapshot:import", headers=headers, json={"markdown": only_modules}
            )
            assert imported.status_code == 200
            assert imported.json()["sections"] == [{"kind": "module", "title": "API"}]
            selection = {
                "interview_direction": "project_overview",
                "selected_sections": [{"kind": "module", "title": "API"}],
            }
            assert (
                await client.put(f"{base}/selection", headers=headers, json=selection)
            ).status_code == 200

            plain = "# Project\nA service with no Module or Thread headings.\n"
            imported = await client.post(
                f"{base}/snapshot:import", headers=headers, json={"markdown": plain}
            )
            assert imported.status_code == 200
            assert imported.json()["sections"] == []
            assert (await client.get(base, headers=headers)).json()["selected_sections"] == []
            selection["selected_sections"] = []
            refused = await client.put(f"{base}/selection", headers=headers, json=selection)
            assert refused.status_code == 400
            assert (await client.get(base, headers=headers)).json()["interview_direction"] is None
            accepted = await client.put(
                f"{base}/selection",
                headers=headers,
                json={**selection, "confirm_empty_range": True},
            )
            assert accepted.status_code == 200
            assert accepted.json()["selected_sections"] == []
            assert accepted.json()["interview_direction"] == "project_overview"
        finally:
            if session_id:
                async with engine.begin() as connection:
                    await connection.execute(
                        text("DELETE FROM app.interview_sessions WHERE id = :id"),
                        {"id": session_id},
                    )


@pytest.mark.asyncio
async def test_import_select_append_and_replay() -> None:
    session_id = None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        user_headers = {"X-Dev-User": USER_ID}
        admin_headers = {"X-Dev-User": ADMIN_ID}
        try:
            created = await client.post("/v1/interviews", headers=user_headers)
            assert created.status_code == 201, created.text
            session_id = created.json()["id"]
            assert created.json()["status"] == "preparing"
            assert (
                await client.get(f"/v1/interviews/{session_id}", headers=admin_headers)
            ).status_code == 403

            imported = await client.post(
                f"/v1/interviews/{session_id}/snapshot:import",
                headers=user_headers,
                json={"markdown": MARKDOWN + "api_key = 'sk-123456789012345678901234'\n"},
            )
            assert imported.status_code == 200, imported.text
            snapshot = imported.json()
            assert "sk-123456789012345678901234" not in snapshot["content"]
            assert snapshot["sections"] == [
                {"kind": "module", "title": "API"},
                {"kind": "thread", "title": "Query Flow"},
            ]
            assert (
                await client.get(f"/v1/interviews/{session_id}/snapshot.md", headers=user_headers)
            ).text == snapshot["content"]

            selection = {
                "interview_direction": "core_flow_deep_dive",
                "selected_sections": [{"kind": "thread", "title": "Query Flow"}],
            }
            bad_selection = {
                **selection,
                "selected_sections": [{"kind": "thread", "title": "Unknown"}],
            }
            assert (
                await client.put(
                    f"/v1/interviews/{session_id}/selection",
                    headers=user_headers,
                    json=bad_selection,
                )
            ).status_code == 400
            selected = await client.put(
                f"/v1/interviews/{session_id}/selection", headers=user_headers, json=selection
            )
            assert selected.status_code == 200, selected.text
            assert selected.json()["selected_sections"] == selection["selected_sections"]

            replay = await client.post(
                f"/v1/interviews/{session_id}/snapshot:import",
                headers=user_headers,
                json={"markdown": MARKDOWN + "api_key = 'sk-123456789012345678901234'\n"},
            )
            assert replay.status_code == 200
            current = await client.get(f"/v1/interviews/{session_id}", headers=user_headers)
            assert current.json()["selected_sections"] == selection["selected_sections"]

            opinion_key = str(uuid4())
            opinion_headers = {**user_headers, "Idempotency-Key": opinion_key}
            opinion_url = f"/v1/interviews/{session_id}/snapshot:append-user-opinion"
            first = await client.post(
                opinion_url, headers=opinion_headers, json={"text": "目前使用 PostgreSQL。"}
            )
            second = await client.post(
                opinion_url, headers=opinion_headers, json={"text": "目前使用 PostgreSQL。"}
            )
            assert first.status_code == second.status_code == 200
            assert first.json()["content"] == second.json()["content"]
            assert first.json()["content"].count("目前使用 PostgreSQL。") == 1
            assert (
                await client.post(opinion_url, headers=opinion_headers, json={"text": "另一个内容"})
            ).status_code == 409
            current = await client.get(f"/v1/interviews/{session_id}", headers=user_headers)
            assert current.json()["selected_sections"] == []

            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "UPDATE app.interview_sessions SET status = 'interviewing' WHERE id = :id"
                    ),
                    {"id": session_id},
                )
            assert (
                await client.post(
                    f"/v1/interviews/{session_id}/snapshot:import",
                    headers=user_headers,
                    json={"markdown": MARKDOWN},
                )
            ).status_code == 409
            assert (
                await client.post(
                    opinion_url,
                    headers={**user_headers, "Idempotency-Key": str(uuid4())},
                    json={"text": "迟到观点"},
                )
            ).status_code == 409
            assert (
                await client.put(
                    f"/v1/interviews/{session_id}/selection",
                    headers=user_headers,
                    json=selection,
                )
            ).status_code == 409
            assert (
                await client.post(
                    f"/v1/interviews/{session_id}/snapshot:observe",
                    headers={**user_headers, "Idempotency-Key": str(uuid4())},
                    json={"source_handle": "A" * 43},
                )
            ).status_code == 409
            assert (
                await client.post(
                    f"/v1/interviews/{session_id}/source:choose", headers=user_headers
                )
            ).status_code == 409
            assert (
                await client.post(
                    f"/v1/interviews/{session_id}/plan:generate", headers=user_headers
                )
            ).status_code == 409
        finally:
            if session_id:
                async with engine.begin() as connection:
                    await connection.execute(
                        text("DELETE FROM app.interview_sessions WHERE id = :id"),
                        {"id": session_id},
                    )
