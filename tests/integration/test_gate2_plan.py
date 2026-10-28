"""Planner publish barrier and preparation invalidation through HTTP."""

import httpx
import pytest
from sqlalchemy import text

from app.api.model_dependency import get_model_adapter
from app.db import engine
from app.domain.contracts import InterviewPlan, InterviewStage, SectionRef
from app.main import app
from model_adapter import ModelFailure

USER_ID = "00000000-0000-4000-8000-000000000001"
MARKDOWN = "# Demo\n## Threads\n### Query Flow\n一次请求从输入到输出。\n"


class ControlledPlanner:
    def __init__(self) -> None:
        self.calls = 0

    async def generate_structured(self, **kwargs) -> InterviewPlan:
        self.calls += 1
        plan = InterviewPlan(
            stages=[
                InterviewStage(
                    id=f"stage-{index}",
                    title=f"阶段 {index}",
                    goal="核实真实链路",
                    complete_when="说明证据和取舍",
                    topic_path="system_design",
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


class MissingPlanner:
    async def generate_structured(self, **_kwargs) -> InterviewPlan:
        raise ModelFailure("dependency_unavailable")


@pytest.mark.asyncio
async def test_plan_publish_replay_and_invalidation() -> None:
    session_id = None
    headers = {"X-Dev-User": USER_ID}
    planner = ControlledPlanner()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        try:
            created = await client.post("/v1/interviews", headers=headers)
            assert created.status_code == 201, created.text
            session_id = created.json()["id"]
            url = f"/v1/interviews/{session_id}"
            assert (
                await client.post(
                    f"{url}/snapshot:import", headers=headers, json={"markdown": MARKDOWN}
                )
            ).status_code == 200
            selection = {
                "interview_direction": "core_flow_deep_dive",
                "selected_sections": [{"kind": "thread", "title": "Query Flow"}],
            }
            assert (
                await client.put(f"{url}/selection", headers=headers, json=selection)
            ).status_code == 200
            app.dependency_overrides[get_model_adapter] = lambda: MissingPlanner()
            unavailable = await client.post(f"{url}/plan:generate", headers=headers)
            assert unavailable.status_code == 503
            assert unavailable.json()["error"]["code"] == "dependency_unavailable"

            app.dependency_overrides[get_model_adapter] = lambda: planner
            generated = await client.post(f"{url}/plan:generate", headers=headers)
            assert generated.status_code == 200, generated.text
            assert len(generated.json()["stages"]) == 5
            assert (await client.post(f"{url}/plan:generate", headers=headers)).status_code == 200
            assert planner.calls == 1
            assert (await client.put(f"{url}/selection", headers=headers, json=selection)).json()[
                "has_plan"
            ]
            assert (
                await client.post(
                    f"{url}/snapshot:import", headers=headers, json={"markdown": MARKDOWN}
                )
            ).status_code == 200
            assert (await client.get(url, headers=headers)).json()["has_plan"]
            assert (
                await client.post(
                    f"{url}/snapshot:import",
                    headers=headers,
                    json={"markdown": MARKDOWN + "新事实。\n"},
                )
            ).status_code == 200
            assert (await client.get(f"{url}/plan", headers=headers)).status_code == 404
            assert not (await client.get(url, headers=headers)).json()["has_plan"]
        finally:
            app.dependency_overrides.pop(get_model_adapter, None)
            if session_id:
                async with engine.begin() as connection:
                    await connection.execute(
                        text("DELETE FROM app.interview_sessions WHERE id = :id"),
                        {"id": session_id},
                    )
