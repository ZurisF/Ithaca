"""Gate 3 entry through public HTTP and the real PostgreSQL/Redis boundaries."""

import json
from uuid import UUID, uuid4

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text

from app.api.model_dependency import get_model_adapter
from app.bank.retrieval import QuestionCandidate, get_retriever
from app.db import engine
from app.domain.contracts import (
    InterviewPlan,
    InterviewStage,
    SectionRef,
    SupervisorDecision,
)
from app.main import app
from app.services import interview as interview_service
from app.settings import get_settings
from model_adapter import ModelFailure

USER_ID = "00000000-0000-4000-8000-000000000001"
SNAPSHOT = "# 项目\n## Threads\n### Query Flow\n输入经过路由和检索后得到回答。\n"


class ControlledModel:
    def __init__(self, question: str) -> None:
        self.question = question
        self.supervisor_calls = 0
        self.seen_candidates: list[str] = []

    async def generate_structured(self, **kwargs):
        if kwargs["operation"] == "planner":
            plan = InterviewPlan(
                stages=[
                    InterviewStage(
                        id=f"stage-{index}",
                        title=f"阶段 {index}",
                        goal="解释检索链路",
                        complete_when="给出证据",
                        topic_path="rag",
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
        self.supervisor_calls += 1
        payload = json.loads(kwargs["messages"][1].content)
        self.seen_candidates = payload["retrieved_questions"]
        assert "question_id" not in kwargs["messages"][1].content
        decision = SupervisorDecision(
            user_acts=[],
            interviewer_message=None,
            plan_action="continue",
            question=self.question,
        )
        assert kwargs["validate_output"](decision) == []
        return decision


class ControlledRetriever:
    def __init__(self, question_id: UUID, question: str, *, fail: bool = False) -> None:
        self.question_id = question_id
        self.question = question
        self.fail = fail
        self.queries: list[tuple[str, str]] = []

    async def retrieve_for_turn(self, session_id, query_text, topic_path, limit=3):
        self.queries.append((query_text, topic_path))
        if self.fail:
            raise TimeoutError("controlled retrieval timeout")
        return [QuestionCandidate(self.question_id, self.question)]


class FailOnceModel(ControlledModel):
    async def generate_structured(self, **kwargs):
        if kwargs["operation"] == "supervisor_stage_entry" and self.supervisor_calls == 0:
            self.supervisor_calls += 1
            raise ModelFailure("provider_transport", retryable=True)
        return await super().generate_structured(**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["exact", "rewritten", "retrieval_timeout"])
async def test_first_question_publication_and_replay(
    mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    question_id = uuid4()
    candidate = f"如何验证检索链路 {question_id.hex[:8]}？"
    actual = candidate if mode == "exact" else f"请解释检索链路 {question_id.hex[:8]}。"
    model = ControlledModel(actual)
    retriever = ControlledRetriever(question_id, candidate, fail=mode == "retrieval_timeout")
    app.dependency_overrides[get_model_adapter] = lambda: model
    app.dependency_overrides[get_retriever] = lambda: retriever
    session_id = None
    notifications = 0
    headers = {"X-Dev-User": USER_ID}

    async def dropped_notification(_session_id) -> None:
        nonlocal notifications
        notifications += 1
        async with engine.connect() as connection:
            published = await connection.scalar(
                text("""
                SELECT count(*) FROM app.turns WHERE session_id = :id
            """),
                {"id": _session_id},
            )
            assert published == 1  # A separate transaction can see the turn before SSE.

    monkeypatch.setattr(interview_service, "notify_current_changed", dropped_notification)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("""
                INSERT INTO bank.questions (id, question, topic_path)
                VALUES (:id, :question, 'rag')
            """),
                {"id": question_id, "question": candidate},
            )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
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
            assert (await client.post(f"{base}/plan:generate", headers=headers)).status_code == 200
            first = await client.post(f"{base}/start", headers=headers)
            assert first.status_code == 200, first.text
            assert first.json()["session"]["status"] == "interviewing"
            assert first.json()["awaiting"] == "answer"
            assert first.json()["current_turn"]["question"] == actual
            assert first.json()["current_turn"]["turn_no"] == 1
            assert first.json()["current_stage_index"] == 0
            assert retriever.queries == [("解释检索链路", "rag")]
            assert model.seen_candidates == ([] if mode == "retrieval_timeout" else [candidate])
            replay = await client.post(f"{base}/start", headers=headers)
            assert replay.status_code == 200, replay.text
            assert replay.json()["current_turn"]["question"] == actual
            assert model.supervisor_calls == 1
            assert notifications == 1
            # The current view is authoritative even when the SSE notification was never received.
            reread = await client.get(f"{base}/current", headers=headers)
            assert reread.status_code == 200
            assert reread.json()["current_turn"]["question"] == actual
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("""
                SELECT turn_no, question_id FROM app.turns WHERE session_id = :id
            """),
                {"id": session_id},
            )
            assert rows.all() == [(1, question_id if mode == "exact" else None)]
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
            if session_id:
                await connection.execute(
                    text("DELETE FROM app.interview_sessions WHERE id = :id"), {"id": session_id}
                )
            await connection.execute(
                text("DELETE FROM bank.questions WHERE id = :id"), {"id": question_id}
            )


@pytest.mark.asyncio
async def test_supervisor_failure_requires_explicit_retry() -> None:
    model = FailOnceModel("请解释你实现的检索链路。")
    retriever = ControlledRetriever(uuid4(), "如何设计检索链路？", fail=True)
    app.dependency_overrides[get_model_adapter] = lambda: model
    app.dependency_overrides[get_retriever] = lambda: retriever
    session_id = None
    headers = {"X-Dev-User": USER_ID}
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post("/v1/interviews", headers=headers)
            assert created.status_code == 201
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
            assert (await client.post(f"{base}/plan:generate", headers=headers)).status_code == 200
            failed = await client.post(f"{base}/start", headers=headers)
            assert failed.status_code == 200
            assert failed.json()["awaiting"] == "decision_retry"
            assert failed.json()["last_error_code"] == "provider_transport"
            assert failed.json()["current_turn"] is None
            duplicate = await client.post(f"{base}/start", headers=headers)
            assert duplicate.json()["awaiting"] == "decision_retry"
            assert model.supervisor_calls == 1
            recovered = await client.post(f"{base}/decision:retry", headers=headers)
            assert recovered.status_code == 200, recovered.text
            assert recovered.json()["awaiting"] == "answer"
            assert recovered.json()["current_turn"]["turn_no"] == 1
            assert model.supervisor_calls == 2
            assert (await client.post(f"{base}/decision:retry", headers=headers)).status_code == 409
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
                    text("DELETE FROM app.interview_sessions WHERE id = :id"), {"id": session_id}
                )
