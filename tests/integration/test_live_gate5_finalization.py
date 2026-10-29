"""Opt-in Gate 5 replay with a real model and synthetic project material."""

import os

import pytest
from test_gate4_interview import HEADERS, Harness, ScriptedModel

from app.api.model_dependency import get_model_adapter
from app.services.finalization import run_finalization

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_GATE5") != "1", reason="opt-in real post-processing replay"
)


@pytest.mark.asyncio
async def test_live_project_ideal_evaluation_and_report():
    async with Harness(ScriptedModel()) as harness:
        session_id, base, _ = await harness.create()
        answered = await harness.answer(
            base,
            1,
            "结束阶段。项目先做关键词与向量召回，再按 RRF 融合并重排；"
            "用固定查询集检查 Recall@K 与 nDCG@K。",
        )
        assert answered.status_code == 200, answered.text
        ended = await harness.client.post(f"{base}/finish-early", headers=HEADERS)
        assert ended.status_code == 200, ended.text
        await run_finalization(session_id, get_model_adapter())
        response = await harness.client.get(f"{base}/full-qa", headers=HEADERS)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["session"]["status"] == "completed"
        assert result["report"] is not None, result
        assert result["processing_incomplete"] is False
        assert result["turns"][0]["project_answer"]
        assert result["turns"][0]["ideal_answer"]
        assert result["turns"][0]["comment"]
        assert result["turns"][1]["answer"] is None
        assert result["turns"][1]["comment"] is None
        for path in ("snapshot.md", "full-qa.md", "report.md"):
            export = await harness.client.get(f"{base}/{path}", headers=HEADERS)
            assert export.status_code == 200 and export.text
