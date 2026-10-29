"""Opt-in Gate 5 Local Runtime source-handle replay with synthetic files."""

import os
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from test_gate4_interview import HEADERS, SNAPSHOT, Harness
from test_gate5_basic import PostModel

from app.services.finalization import run_finalization
from app.settings import get_settings

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_GATE5_LOCAL") != "1",
    reason="requires Local Runtime process and real local project model",
)


class LocalRequiredModel(PostModel):
    def __init__(self, *, require_local: bool):
        super().__init__()
        self.require_local = require_local
        self.fallback_calls = 0

    async def generate_structured(self, **kwargs):
        if kwargs["operation"] == "project_answers":
            self.fallback_calls += 1
            if self.require_local:
                raise RuntimeError("Local Runtime must handle project answers")
        return await super().generate_structured(**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("release_before_finalization", [False, True])
async def test_local_project_answers_use_or_fall_back_from_authorized_handle(
    tmp_path: Path, release_before_finalization: bool
):
    source = tmp_path / "synthetic_project"
    source.mkdir()
    (source / "README.md").write_text(
        "# Synthetic Project\n## Threads\n### Query Flow\n"
        "Requests use lexical and vector retrieval, fuse candidates with RRF, "
        "then rerank. The fixed query set measures Recall@K and nDCG@K.\n",
        encoding="utf-8",
    )
    settings = get_settings()
    model = LocalRequiredModel(require_local=not release_before_finalization)
    async with (
        Harness(model) as harness,
        httpx.AsyncClient(
            base_url=settings.local_runtime_url, timeout=210, trust_env=False
        ) as local,
    ):
        created = await harness.client.post("/v1/interviews", headers=HEADERS)
        assert created.status_code == 201, created.text
        session_id = UUID(created.json()["id"])
        harness.ids.append(session_id)
        base = f"/v1/interviews/{session_id}"
        local_headers = {"Authorization": f"Bearer {settings.desktop_instance_token}"}
        authorized = await local.post(
            "/v1/sources:authorize",
            headers=local_headers,
            json={"session_id": str(session_id), "path": str(source)},
        )
        assert authorized.status_code == 200, authorized.text
        handle = authorized.json()["source_handle"]
        try:
            imported = await harness.client.post(
                f"{base}/snapshot:import",
                headers=HEADERS,
                json={"markdown": SNAPSHOT, "source_handle": handle},
            )
            assert imported.status_code == 200, imported.text
            selected = await harness.client.put(
                f"{base}/selection",
                headers=HEADERS,
                json={
                    "interview_direction": "core_flow_deep_dive",
                    "selected_sections": [{"kind": "thread", "title": "Query Flow"}],
                },
            )
            assert selected.status_code == 200, selected.text
            assert (
                await harness.client.post(f"{base}/plan:generate", headers=HEADERS)
            ).status_code == 200
            assert (await harness.client.post(f"{base}/start", headers=HEADERS)).status_code == 200
            assert (
                await harness.answer(base, 1, "结束阶段；项目用 RRF 融合检索结果。 ")
            ).status_code == 200
            assert (
                await harness.client.post(f"{base}/finish-early", headers=HEADERS)
            ).status_code == 200
            if release_before_finalization:
                released = await local.delete(
                    f"/v1/sources/{handle}",
                    headers=local_headers,
                    params={"session_id": str(session_id)},
                )
                assert released.status_code == 200
            await run_finalization(session_id, model)
            result = (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()
            assert model.fallback_calls == int(release_before_finalization)
            assert result["session"]["status"] == "completed"
            assert result["turns"][0]["project_answer"]
            assert result["turns"][0]["comment"]
            assert result["report"] is not None
            if release_before_finalization:
                snapshot = await harness.client.get(f"{base}/snapshot.md", headers=HEADERS)
                assert snapshot.text == SNAPSHOT
        finally:
            if not release_before_finalization:
                await local.delete(
                    f"/v1/sources/{handle}",
                    headers=local_headers,
                    params={"session_id": str(session_id)},
                )
