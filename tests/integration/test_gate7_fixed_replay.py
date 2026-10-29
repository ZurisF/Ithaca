"""Frozen three-project HTTP replay through plan, Stage transition and early finish."""

import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text

from app.api.model_dependency import get_model_adapter
from app.bank.retrieval import get_retriever
from app.db import engine
from app.domain.contracts import InterviewPlan, InterviewStage, SectionRef, SupervisorDecision
from app.main import app
from app.services.interview_checkpoint import delete_checkpoint

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/gate7"
PROJECTS = json.loads((FIXTURES / "projects.json").read_text(encoding="utf-8"))
HEADERS = {"X-Dev-User": "00000000-0000-4000-8000-000000000001"}


class EmptyRetriever:
    async def retrieve_for_turn(self, *_args, **_kwargs):
        return []


class ReplayModel:
    def __init__(self, project: dict) -> None:
        self.project = project
        self.operations: list[str] = []

    async def generate_structured(self, **kwargs):
        operation = kwargs["operation"]
        self.operations.append(operation)
        if operation == "planner":
            assert self.project["fact"] in kwargs["messages"][1].content
            plan = InterviewPlan(
                stages=[
                    InterviewStage(
                        id=f"{self.project['id']}-{index}",
                        title=f"{self.project['section']} {index + 1}",
                        goal=f"Explain {self.project['section']} using project evidence",
                        complete_when="Give a concrete project-based explanation",
                        topic_path=self.project["topic"],
                        section_refs=[SectionRef(kind="thread", title=self.project["section"])],
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
        payload = json.loads(kwargs["messages"][1].content)
        assert self.project["fact"] in json.dumps(payload, ensure_ascii=False)
        if operation == "supervisor_stage_entry":
            decision = SupervisorDecision(
                user_acts=[],
                interviewer_message=None,
                plan_action="continue",
                question=self.project["question"],
            )
        else:
            assert payload["current_answered_turn"]["answer"] == self.project["answer"]
            decision = SupervisorDecision(
                user_acts=[{"type": "answer"}],
                interviewer_message="The explanation covers this Stage.",
                plan_action="complete",
                question=None,
            )
        assert kwargs["validate_output"](decision) == []
        return decision


@pytest.mark.asyncio
@pytest.mark.parametrize("project", PROJECTS, ids=[item["id"] for item in PROJECTS])
@pytest.mark.parametrize("repeat", [1, 2])
async def test_fixed_project_replay_is_repeatable(project: dict, repeat: int) -> None:
    del repeat  # The same frozen case is intentionally run twice.
    snapshot = (FIXTURES / project["snapshot"]).read_text(encoding="utf-8")
    if project["source_root"]:
        assert (ROOT / project["source_root"]).is_dir()
    assert project["fact"] in snapshot
    model = ReplayModel(project)
    app.dependency_overrides[get_model_adapter] = lambda: model
    app.dependency_overrides[get_retriever] = EmptyRetriever
    session_id: UUID | None = None
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            created = await client.post("/v1/interviews", headers=HEADERS)
            assert created.status_code == 201, created.text
            session_id = UUID(created.json()["id"])
            base = f"/v1/interviews/{session_id}"
            imported = await client.post(
                f"{base}/snapshot:import", headers=HEADERS, json={"markdown": snapshot}
            )
            assert imported.status_code == 200, imported.text
            assert imported.json()["content"] == snapshot
            selected = await client.put(
                f"{base}/selection",
                headers=HEADERS,
                json={
                    "interview_direction": "core_flow_deep_dive",
                    "selected_sections": [{"kind": "thread", "title": project["section"]}],
                },
            )
            assert selected.status_code == 200, selected.text
            planned = await client.post(f"{base}/plan:generate", headers=HEADERS)
            assert planned.status_code == 200, planned.text
            assert len(planned.json()["stages"]) == 5
            assert (
                await client.post(f"{base}/plan:generate", headers=HEADERS)
            ).json() == planned.json()
            started = await client.post(f"{base}/start", headers=HEADERS)
            assert started.status_code == 200, started.text
            assert started.json()["current_turn"]["question"] == project["question"]
            answered = await client.post(
                f"{base}/answers",
                headers=HEADERS,
                json={"turn_no": 1, "answer": project["answer"]},
            )
            assert answered.status_code == 200, answered.text
            assert answered.json()["current_stage_index"] == 1
            assert answered.json()["current_turn"]["turn_no"] == 2
            assert answered.json()["current_turn"]["question"] == project["question"]
            reread = await client.get(f"{base}/current", headers=HEADERS)
            assert reread.status_code == 200
            assert reread.json()["current_turn"] == answered.json()["current_turn"]
            assert model.operations == [
                "planner",
                "supervisor_stage_entry",
                "supervisor_answer",
                "supervisor_stage_entry",
            ]
    finally:
        app.dependency_overrides.pop(get_model_adapter, None)
        app.dependency_overrides.pop(get_retriever, None)
        if session_id is not None:
            await delete_checkpoint(session_id)
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM app.interview_sessions WHERE id = :id"), {"id": session_id}
                )
