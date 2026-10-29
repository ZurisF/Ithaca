"""Opt-in two-process Gate 5 worker replay and Local trace forwarding."""

import asyncio
import os
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from test_gate4_interview import HEADERS, SNAPSHOT, Harness, ScriptedModel

from app.db import engine
from app.settings import get_settings

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_GATE5_WORKER_HTTP") != "1",
    reason="requires Application and Local Runtime processes with configured model",
)


@pytest.mark.asyncio
async def test_worker_finishes_local_source_session_and_forwards_trace(tmp_path: Path):
    source = tmp_path / "synthetic_project"
    source.mkdir()
    (source / "README.md").write_text(
        "# Synthetic Project\n## Threads\n### Query Flow\n"
        "The query path combines lexical and vector retrieval using RRF, then reranks. "
        "A fixed evaluation set measures Recall@K and nDCG@K.\n",
        encoding="utf-8",
    )
    settings = get_settings()
    local_headers = {"Authorization": f"Bearer {settings.desktop_instance_token}"}
    async with (
        Harness(ScriptedModel()) as harness,
        httpx.AsyncClient(
            base_url=settings.local_runtime_url, timeout=20, trust_env=False
        ) as local,
        httpx.AsyncClient(
            base_url="http://127.0.0.1:8100", timeout=20, trust_env=False
        ) as application,
    ):
        created = await harness.client.post("/v1/interviews", headers=HEADERS)
        assert created.status_code == 201, created.text
        session_id = UUID(created.json()["id"])
        harness.ids.append(session_id)
        base = f"/v1/interviews/{session_id}"
        authorized = await local.post(
            "/v1/sources:authorize",
            headers=local_headers,
            json={"session_id": str(session_id), "path": str(source)},
        )
        assert authorized.status_code == 200, authorized.text
        handle = authorized.json()["source_handle"]
        try:
            assert (
                await harness.client.post(
                    f"{base}/snapshot:import",
                    headers=HEADERS,
                    json={"markdown": SNAPSHOT, "source_handle": handle},
                )
            ).status_code == 200
            assert (
                await harness.client.put(
                    f"{base}/selection",
                    headers=HEADERS,
                    json={
                        "interview_direction": "core_flow_deep_dive",
                        "selected_sections": [{"kind": "thread", "title": "Query Flow"}],
                    },
                )
            ).status_code == 200
            assert (
                await harness.client.post(f"{base}/plan:generate", headers=HEADERS)
            ).status_code == 200
            assert (await harness.client.post(f"{base}/start", headers=HEADERS)).status_code == 200
            assert (
                await harness.answer(base, 1, "结束阶段；项目用 RRF 融合并重排检索结果。 ")
            ).status_code == 200
            assert (
                await harness.client.post(f"{base}/finish-early", headers=HEADERS)
            ).status_code == 200

            async def wait_completed():
                while True:
                    response = await application.get(f"{base}/full-qa", headers=HEADERS)
                    assert response.status_code == 200, response.text
                    result = response.json()
                    if result["session"]["status"] == "completed":
                        return result
                    await asyncio.sleep(0.5)

            result = await asyncio.wait_for(wait_completed(), timeout=180)
            assert result["report"] is not None, result
            assert result["turns"][0]["project_answer"]
            assert result["turns"][0]["ideal_answer"]
            assert result["turns"][0]["comment"]
            async with engine.connect() as connection:
                calls = (
                    (
                        await connection.execute(
                            text("""
                    SELECT operation_name FROM telemetry.model_calls
                    WHERE session_id = :id
                """),
                            {"id": session_id},
                        )
                    )
                    .scalars()
                    .all()
                )
            assert "project_answers_local" in calls
            assert "report" in calls
        finally:
            await local.delete(
                f"/v1/sources/{handle}",
                headers=local_headers,
                params={"session_id": str(session_id)},
            )
