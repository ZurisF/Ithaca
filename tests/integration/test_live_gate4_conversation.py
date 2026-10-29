"""Opt-in real Supervisor replay across follow-up and Stage transition."""

import os

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text

from app.api.model_dependency import get_model_adapter
from app.bank.retrieval import get_retriever
from app.db import engine
from app.domain.contracts import InterviewPlan, InterviewStage, SectionRef
from app.main import app
from app.settings import get_settings

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_GATE4") != "1", reason="opt-in real Supervisor replay"
)
USER_ID = "00000000-0000-4000-8000-000000000001"
SNAPSHOT = (
    "# Query Lab\n## Threads\n### Query Flow\n"
    "项目先以 BGE-M3 生成查询向量，与 PostgreSQL 全文检索并行召回，"
    "用 RRF 融合结果，再由本机 reranker 重排。离线固定查询集看 Recall@K、nDCG@K；"
    "线上按问题冷却避免重复。\n"
)


class FixedPlanner:
    async def generate_structured(self, **kwargs):
        plan = InterviewPlan(
            stages=[
                InterviewStage(
                    id=f"stage-{index}",
                    title="检索链路" if index == 0 else f"阶段 {index}",
                    goal="解释本项目混合检索的流程、验证方式及取舍"
                    if index == 0
                    else "解释项目工程决策",
                    complete_when="说明向量和关键词融合、重排、Recall@K/nDCG@K 以及成本取舍"
                    if index == 0
                    else "给出可验证的工程证据",
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


class NoCandidates:
    async def retrieve_for_turn(self, *_args, **_kwargs):
        return []


@pytest.mark.asyncio
async def test_live_supervisor_continues_then_closes_stage():
    session_id = None
    headers = {"X-Dev-User": USER_ID}
    app.dependency_overrides[get_retriever] = lambda: NoCandidates()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=120
    ) as client:
        try:
            created = await client.post("/v1/interviews", headers=headers)
            assert created.status_code == 201, created.text
            session_id = created.json()["id"]
            base = f"/v1/interviews/{session_id}"
            assert (
                await client.post(
                    f"{base}/snapshot:import", headers=headers, json={"markdown": SNAPSHOT}
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
            app.dependency_overrides[get_model_adapter] = lambda: FixedPlanner()
            assert (await client.post(f"{base}/plan:generate", headers=headers)).status_code == 200
            app.dependency_overrides.pop(get_model_adapter, None)
            started = await client.post(f"{base}/start", headers=headers)
            assert started.status_code == 200, started.text
            assert started.json()["awaiting"] == "answer", started.json()
            first = await client.post(
                f"{base}/answers",
                headers=headers,
                json={"turn_no": 1, "answer": "我们同时使用向量和关键词检索。"},
            )
            assert first.status_code == 200, first.text
            assert first.json()["awaiting"] == "answer", first.json()
            assert first.json()["current_turn"]["turn_no"] == 2
            complete_answer = (
                "查询先经 BGE-M3 编码，向量检索与 PostgreSQL 全文检索各取候选；"
                "RRF 按名次融合，避免分数尺度不可比，然后本机 reranker 重新排序。"
                "固定查询集用 Recall@K 检查召回覆盖，nDCG@K 检查排序质量，并单独看重复率。"
                "取舍是重排增加计算延迟，但减少不相关问题；候选数受预算控制，"
                "检索超时降级为空候选，由面试官自行生成问题。"
            )
            second = await client.post(
                f"{base}/answers",
                headers=headers,
                json={"turn_no": 2, "answer": complete_answer},
            )
            assert second.status_code == 200, second.text
            assert second.json()["current_stage_index"] == 1, second.json()
            assert second.json()["current_turn"]["stage_index"] == 1
            reread = await client.get(f"{base}/current", headers=headers)
            assert reread.json()["current_turn"] == second.json()["current_turn"]
        finally:
            app.dependency_overrides.pop(get_model_adapter, None)
            app.dependency_overrides.pop(get_retriever, None)
            if session_id:
                redis = Redis.from_url(get_settings().redis_url)
                try:
                    await redis.delete(f"interview:{session_id}:checkpoint")
                finally:
                    await redis.aclose()
                async with engine.begin() as connection:
                    await connection.execute(
                        text("DELETE FROM app.interview_sessions WHERE id = :id"),
                        {"id": session_id},
                    )
