"""Opt-in first-question replay: controlled plan, real retrieval and real Supervisor."""

import os
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text

from app.api.model_dependency import get_model_adapter
from app.db import engine
from app.domain.contracts import InterviewPlan, InterviewStage, SectionRef
from app.main import app
from app.services.interview_checkpoint import delete_checkpoint

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_GATE3") != "1", reason="opt-in model-provider replay"
)
USER_ID = "00000000-0000-4000-8000-000000000001"


class ControlledPlanner:
    async def generate_structured(self, **kwargs):
        plan = InterviewPlan(
            stages=[
                InterviewStage(
                    id=f"stage-{index}",
                    title=f"阶段 {index}",
                    goal="解释项目检索链路如何保证召回质量与重排准确性",
                    complete_when="说清设计、验证指标和取舍",
                    topic_path="rag.retrieval",
                    section_refs=[SectionRef(kind="thread", title="Query Flow")],
                )
                for index in range(5)
            ],
            template_id="core_flow_deep_dive",
            template_version="v1",
            topic_registry_version="v1",
            planning_policy_version="v1",
        )
        assert kwargs["validate_output"](plan) == []
        return plan


@pytest.mark.asyncio
async def test_live_first_question_is_visible_after_start() -> None:
    session_id = None
    headers = {"X-Dev-User": USER_ID}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=120
    ) as client:
        try:
            created = await client.post("/v1/interviews", headers=headers)
            assert created.status_code == 201, created.text
            session_id = created.json()["id"]
            base = f"/v1/interviews/{session_id}"
            snapshot = (
                "# 项目\n## Threads\n### Query Flow\n"
                "请求先进行意图识别，再使用向量与关键词混合检索，重排后生成回答。\n"
            )
            assert (
                await client.post(
                    f"{base}/snapshot:import", headers=headers, json={"markdown": snapshot}
                )
            ).status_code == 200
            assert (
                await client.put(
                    f"{base}/selection",
                    headers=headers,
                    json={
                        "interview_direction": "core_flow_deep_dive",
                        "selected_sections": [{"kind": "thread", "title": "Query Flow"}],
                    },
                )
            ).status_code == 200
            app.dependency_overrides[get_model_adapter] = lambda: ControlledPlanner()
            assert (await client.post(f"{base}/plan:generate", headers=headers)).status_code == 200
            app.dependency_overrides.pop(get_model_adapter, None)
            started = await client.post(f"{base}/start", headers=headers)
            assert started.status_code == 200, started.text
            assert started.json()["awaiting"] == "answer", started.json()
            assert started.json()["current_turn"]["question"].strip()
            reread = await client.get(f"{base}/current", headers=headers)
            assert reread.json()["current_turn"] == started.json()["current_turn"]
        finally:
            app.dependency_overrides.pop(get_model_adapter, None)
            if session_id:
                await delete_checkpoint(UUID(session_id))
                async with engine.begin() as connection:
                    await connection.execute(
                        text("DELETE FROM app.interview_sessions WHERE id = :id"),
                        {"id": session_id},
                    )
