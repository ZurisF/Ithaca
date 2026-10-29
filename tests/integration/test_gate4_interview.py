"""Gate 4 public commands and PostgreSQL/Redis recovery boundaries."""

import asyncio
import json
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text

from app.api.model_dependency import get_model_adapter
from app.bank.retrieval import get_retriever
from app.db import engine
from app.domain.contracts import InterviewPlan, InterviewStage, SectionRef, SupervisorDecision
from app.main import app
from app.services import interview as service
from app.services import interview_worker as worker
from app.services.interview_checkpoint import delete_checkpoint
from model_adapter import ModelFailure

USER_ID = UUID("00000000-0000-4000-8000-000000000001")
HEADERS = {"X-Dev-User": str(USER_ID)}
SNAPSHOT = "# 项目\n## Threads\n### Query Flow\n输入经过路由和检索后得到回答。\n"


class EmptyRetriever:
    async def retrieve_for_turn(self, *_args, **_kwargs):
        return []


class ScriptedModel:
    def __init__(self):
        self.supervisor_calls = 0
        self.compact_inputs = []
        self.answer_contexts = []
        self.fail_answer_once = False

    async def generate_structured(self, **kwargs):
        operation = kwargs["operation"]
        if operation == "planner":
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
        if operation == "interview_compact":
            payload = json.loads(kwargs["messages"][1].content)
            self.compact_inputs.append(payload)
            numbers = [turn["turn_no"] for turn in payload["turns"]]
            assert len(numbers) == 20
            return kwargs["output_schema"](
                compact=f"{payload['previous_compact'] or ''}|{numbers[0]}..{numbers[-1]}"
            )
        self.supervisor_calls += 1
        payload = json.loads(kwargs["messages"][1].content)
        assert "question_id" not in kwargs["messages"][1].content
        if operation == "supervisor_stage_entry":
            decision = SupervisorDecision(
                user_acts=[],
                interviewer_message=None,
                plan_action="continue",
                question=f"阶段 {payload['current_stage_index']} 的首题？",
            )
        else:
            self.answer_contexts.append(payload)
            answer = payload["current_answered_turn"]["answer"]
            if self.fail_answer_once:
                self.fail_answer_once = False
                raise ModelFailure("provider_transport", retryable=True)
            if "纠正" in answer:
                decision = SupervisorDecision(
                    user_acts=[
                        {"type": "answer"},
                        {"type": "correct_project_fact", "text": "缓存层使用 Redis"},
                    ],
                    interviewer_message="已记录你的说明。",
                    plan_action="continue",
                    question=f"后续问题 {self.supervisor_calls}？",
                )
            elif "结束阶段" in answer:
                decision = SupervisorDecision(
                    user_acts=[{"type": "answer"}],
                    interviewer_message="本阶段已完成。",
                    plan_action="complete",
                    question=None,
                )
            else:
                decision = SupervisorDecision(
                    user_acts=[
                        {"type": "answer"},
                        {"type": "ask_interviewer", "question_kind": "clarification"},
                    ],
                    interviewer_message="请说明召回证据。",
                    plan_action="continue",
                    question=f"后续问题 {self.supervisor_calls}？",
                )
        assert kwargs["validate_output"](decision) == []
        return decision


class BlockingModel(ScriptedModel):
    def __init__(self):
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def generate_structured(self, **kwargs):
        if kwargs["operation"] == "supervisor_answer":
            self.entered.set()
            await self.release.wait()
        return await super().generate_structured(**kwargs)


class Harness:
    def __init__(self, model):
        self.model = model
        self.retriever = EmptyRetriever()
        self.ids = []

    async def __aenter__(self):
        app.dependency_overrides[get_model_adapter] = lambda: self.model
        app.dependency_overrides[get_retriever] = lambda: self.retriever
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        )
        return self

    async def __aexit__(self, *_args):
        await self.client.aclose()
        app.dependency_overrides.pop(get_model_adapter, None)
        app.dependency_overrides.pop(get_retriever, None)
        for session_id in self.ids:
            await delete_checkpoint(session_id)
        async with engine.begin() as connection:
            for session_id in self.ids:
                await connection.execute(
                    text("DELETE FROM app.interview_sessions WHERE id = :id"), {"id": session_id}
                )

    async def create(self):
        response = await self.client.post("/v1/interviews", headers=HEADERS)
        assert response.status_code == 201, response.text
        session_id = UUID(response.json()["id"])
        self.ids.append(session_id)
        base = f"/v1/interviews/{session_id}"
        assert (
            await self.client.post(
                f"{base}/snapshot:import", headers=HEADERS, json={"markdown": SNAPSHOT}
            )
        ).status_code == 200
        assert (
            await self.client.put(
                f"{base}/selection",
                headers=HEADERS,
                json={
                    "interview_direction": "core_flow_deep_dive",
                    "selected_sections": [{"kind": "thread", "title": "Query Flow"}],
                },
            )
        ).status_code == 200
        assert (await self.client.post(f"{base}/plan:generate", headers=HEADERS)).status_code == 200
        started = await self.client.post(f"{base}/start", headers=HEADERS)
        assert started.status_code == 200, started.text
        return session_id, base, started.json()

    async def answer(self, base, turn_no, answer):
        return await self.client.post(
            f"{base}/answers",
            headers=HEADERS,
            json={"turn_no": turn_no, "answer": answer},
        )


@pytest.mark.asyncio
async def test_answer_replay_stage_advance_and_filtered_model_context():
    model = ScriptedModel()
    async with Harness(model) as harness:
        session_id, base, started = await harness.create()
        assert started["current_turn"]["turn_no"] == 1
        raw = "继续回答 secret=abcdefghijk"
        result = await harness.answer(base, 1, raw)
        assert result.status_code == 200, result.text
        assert result.json()["current_turn"]["turn_no"] == 2
        assert result.json()["previous_turn"]["interviewer_message"] == "请说明召回证据。"
        assert "abcdefghijk" not in json.dumps(model.answer_contexts)
        before = model.supervisor_calls
        replay = await harness.answer(base, 1, raw)
        assert replay.status_code == 200
        assert replay.json()["current_turn"]["turn_no"] == 2
        assert model.supervisor_calls == before
        conflict = await harness.answer(base, 1, "不同回答")
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "answer_conflict"
        closed = await harness.answer(base, 2, "结束阶段")
        assert closed.status_code == 200, closed.text
        assert closed.json()["current_stage_index"] == 1
        assert closed.json()["current_turn"]["turn_no"] == 3
        assert closed.json()["current_turn"]["stage_index"] == 1
        assert model.supervisor_calls == 4
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    text("""
                SELECT turn_no, answer FROM app.turns WHERE session_id = :id ORDER BY turn_no
            """),
                    {"id": session_id},
                )
            ).all()
            assert rows[0] == (1, raw)
            assert [item[0] for item in rows] == [1, 2, 3]
            stages = (
                await connection.execute(
                    text("""
                SELECT stage_index, result FROM app.stage_results WHERE session_id = :id
            """),
                    {"id": session_id},
                )
            ).all()
            assert stages == [(0, "complete")]


@pytest.mark.asyncio
async def test_concurrent_same_answer_has_one_supervisor_call():
    model = BlockingModel()
    async with Harness(model) as harness:
        _session_id, base, _ = await harness.create()
        first = asyncio.create_task(harness.answer(base, 1, "继续回答"))
        await asyncio.wait_for(model.entered.wait(), timeout=2)
        overlap = await harness.answer(base, 1, "继续回答")
        assert overlap.status_code in {200, 409}
        model.release.set()
        published = await first
        assert published.status_code == 200, published.text
        replay = await harness.answer(base, 1, "继续回答")
        assert replay.status_code == 200
        assert replay.json()["current_turn"]["turn_no"] == 2
        assert model.supervisor_calls == 2


@pytest.mark.asyncio
async def test_lost_answer_notification_still_reads_committed_question(monkeypatch):
    model = ScriptedModel()
    async with Harness(model) as harness:
        _session_id, base, _ = await harness.create()

        async def drop_notification(_session_id, _event):
            return None

        monkeypatch.setattr(service, "notify_current_changed", drop_notification)
        answered = await harness.answer(base, 1, "继续回答")
        assert answered.status_code == 200, answered.text
        reread = await harness.client.get(f"{base}/current", headers=HEADERS)
        assert reread.status_code == 200
        assert reread.json()["current_turn"]["turn_no"] == 2
        assert reread.json()["current_turn"] == answered.json()["current_turn"]


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["confirm", "do_not_write"])
async def test_snapshot_correction_reuses_same_supervisor_decision(choice):
    model = ScriptedModel()
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()
        pending = await harness.answer(base, 1, "纠正项目事实")
        assert pending.status_code == 200, pending.text
        assert pending.json()["awaiting"] == "snapshot_confirmation"
        assert pending.json()["pending_correction"] == "缓存层使用 Redis"
        assert pending.json()["current_turn"]["turn_no"] == 1
        blocked = await harness.answer(base, 2, "抢先回答下一题")
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "operation_in_progress"
        conflict = await harness.answer(base, 1, "更换已提交的回答")
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "answer_conflict"
        before = model.supervisor_calls
        if choice == "confirm":
            filtered = await harness.client.post(
                f"{base}/snapshot-corrections:resolve",
                headers=HEADERS,
                json={
                    "turn_no": 1,
                    "decision": "confirm",
                    "edited_text": "缓存层使用 Redis secret=abcdefghijk",
                },
            )
            assert filtered.status_code == 200, filtered.text
            assert filtered.json()["awaiting"] == "snapshot_confirmation"
            assert "abcdefghijk" not in filtered.json()["pending_correction"]
            assert model.supervisor_calls == before
        resolved = await harness.client.post(
            f"{base}/snapshot-corrections:resolve",
            headers=HEADERS,
            json={"turn_no": 1, "decision": choice},
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["awaiting"] == "answer"
        assert resolved.json()["current_turn"]["turn_no"] == 2
        assert model.supervisor_calls == before
        async with engine.connect() as connection:
            snapshot = await connection.scalar(
                text("SELECT content FROM app.session_snapshots WHERE session_id = :id"),
                {"id": session_id},
            )
            count = await connection.scalar(
                text("SELECT count(*) FROM app.snapshot_append_operations WHERE session_id = :id"),
                {"id": session_id},
            )
        if choice == "confirm":
            assert "缓存层使用 Redis" in snapshot
            assert "abcdefghijk" not in snapshot
            assert count == 1
        else:
            assert snapshot == SNAPSHOT
            assert count == 0


@pytest.mark.asyncio
async def test_failed_answer_decision_requires_explicit_retry(monkeypatch):
    model = ScriptedModel()
    model.fail_answer_once = True
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()
        failed = await harness.answer(base, 1, "继续回答")
        assert failed.status_code == 200, failed.text
        assert failed.json()["awaiting"] == "decision_retry"
        before = model.supervisor_calls
        assert (await harness.answer(base, 1, "继续回答")).status_code == 200
        assert model.supervisor_calls == before
        conflict = await harness.answer(base, 1, "不同回答")
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "answer_conflict"
        blocked = await harness.answer(base, 2, "抢先回答下一题")
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "operation_in_progress"

        async def selected(_db, _limit=20):
            return [{"id": session_id, "user_id": USER_ID}]

        monkeypatch.setattr(worker, "recoverable_sessions", selected)
        monkeypatch.setattr(worker, "get_model_adapter", lambda: model)
        monkeypatch.setattr(worker, "get_retriever", lambda: harness.retriever)
        assert await worker.recover_once() == 0
        assert model.supervisor_calls == before
        retried = await harness.client.post(f"{base}/decision:retry", headers=HEADERS)
        assert retried.status_code == 200, retried.text
        assert retried.json()["current_turn"]["turn_no"] == 2
        assert model.supervisor_calls == before + 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "crash_point", ["after_answer", "after_model", "after_stage_close", "after_stage_checkpoint"]
)
async def test_worker_resumes_only_missing_effect(crash_point, monkeypatch):
    model = ScriptedModel()
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()
        original_run = service._run_decisions
        original_publish = service._publish_decision
        original_load = service._load_context
        if crash_point == "after_answer":

            async def crash_once(*args):
                monkeypatch.setattr(service, "_run_decisions", original_run)
                raise RuntimeError("simulated process stop after answer commit")

            monkeypatch.setattr(service, "_run_decisions", crash_once)
            answer = "继续回答"
        elif crash_point == "after_model":

            async def crash_once(*args, **kwargs):
                monkeypatch.setattr(service, "_publish_decision", original_publish)
                raise RuntimeError("simulated process stop after Supervisor returned")

            monkeypatch.setattr(service, "_publish_decision", crash_once)
            answer = "继续回答"
        else:
            # The graph reloads context in load_session_context and once more inside
            # after_publication. The stage-close commit sits between the second and
            # third call; the post-node checkpoint write sits after the second call.
            stopped_after_call = 2 if crash_point == "after_stage_close" else 3
            load_calls = 0

            async def crash_on_load(*args, **kwargs):
                nonlocal load_calls
                load_calls += 1
                if load_calls == stopped_after_call:
                    monkeypatch.setattr(service, "_load_context", original_load)
                    raise RuntimeError("simulated process stop around stage close")
                return await original_load(*args, **kwargs)

            monkeypatch.setattr(service, "_load_context", crash_on_load)
            answer = "结束阶段"
        interrupted = await harness.answer(base, 1, answer)
        assert interrupted.status_code == 500
        before = model.supervisor_calls
        checkpoint = await service.read_checkpoint(session_id)
        if crash_point == "after_stage_close":
            # The close committed but the graph node never finished: no checkpoint advance.
            assert checkpoint["route"] == "continue"
        if crash_point == "after_stage_checkpoint":
            # The node completed and its checkpoint write persisted the stage change.
            assert checkpoint["route"] == "next_stage"

        async def selected(_db, _limit=20):
            return [{"id": session_id, "user_id": USER_ID}]

        monkeypatch.setattr(worker, "recoverable_sessions", selected)
        monkeypatch.setattr(worker, "get_model_adapter", lambda: model)
        monkeypatch.setattr(worker, "get_retriever", lambda: harness.retriever)
        assert await worker.recover_once() == 1
        current = await harness.client.get(f"{base}/current", headers=HEADERS)
        assert current.status_code == 200
        assert current.json()["current_turn"]["turn_no"] == 2
        assert model.supervisor_calls == before + 1
        if crash_point in {"after_stage_close", "after_stage_checkpoint"}:
            assert current.json()["current_stage_index"] == 1


@pytest.mark.asyncio
async def test_cumulative_compact_rebuilds_after_checkpoint_loss():
    model = ScriptedModel()
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()
        for turn_no in range(1, 41):
            response = await harness.answer(base, turn_no, f"继续回答 第{turn_no}题")
            assert response.status_code == 200, (turn_no, response.text)
            assert response.json()["current_turn"]["turn_no"] == turn_no + 1
        assert len(model.compact_inputs) == 2
        assert model.compact_inputs[0]["previous_compact"] is None
        assert model.compact_inputs[1]["previous_compact"] == "|1..20"
        assert model.answer_contexts[-1]["compact"] == "|1..20|21..40"
        assert model.answer_contexts[-1]["recent_turns"] == []
        await delete_checkpoint(session_id)
        response = await harness.answer(base, 41, "继续回答 第41题")
        assert response.status_code == 200, response.text
        assert len(model.compact_inputs) == 4
        assert model.compact_inputs[2]["previous_compact"] is None
        assert model.compact_inputs[3]["previous_compact"] == "|1..20"
        assert model.answer_contexts[-1]["compact"] == "|1..20|21..40"
        assert [item["turn_no"] for item in model.answer_contexts[-1]["recent_turns"]] == [41]


@pytest.mark.asyncio
async def test_confirmed_append_survives_lost_checkpoint_before_question(monkeypatch):
    model = ScriptedModel()
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()
        pending = await harness.answer(base, 1, "纠正项目事实")
        assert pending.json()["awaiting"] == "snapshot_confirmation"
        original_publish = service._publish_decision

        async def crash_once(*args, **kwargs):
            monkeypatch.setattr(service, "_publish_decision", original_publish)
            raise RuntimeError("simulated stop after correction append")

        monkeypatch.setattr(service, "_publish_decision", crash_once)
        interrupted = await harness.client.post(
            f"{base}/snapshot-corrections:resolve",
            headers=HEADERS,
            json={"turn_no": 1, "decision": "confirm"},
        )
        assert interrupted.status_code == 500
        await delete_checkpoint(session_id)

        async def selected(_db, _limit=20):
            return [{"id": session_id, "user_id": USER_ID}]

        monkeypatch.setattr(worker, "recoverable_sessions", selected)
        monkeypatch.setattr(worker, "get_model_adapter", lambda: model)
        monkeypatch.setattr(worker, "get_retriever", lambda: harness.retriever)
        assert await worker.recover_once() == 1
        current = await harness.client.get(f"{base}/current", headers=HEADERS)
        assert current.json()["current_turn"]["turn_no"] == 2
        async with engine.connect() as connection:
            count = await connection.scalar(
                text("SELECT count(*) FROM app.snapshot_append_operations WHERE session_id = :id"),
                {"id": session_id},
            )
            assert count == 1


@pytest.mark.asyncio
async def test_turn_100_stops_before_creating_turn_101(monkeypatch):
    model = ScriptedModel()
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()
        async with engine.begin() as connection:
            await connection.execute(
                text("""
                UPDATE app.turns SET answer = '继续回答 第1题', answered_at = now()
                WHERE session_id = :id AND turn_no = 1
            """),
                {"id": session_id},
            )
            await connection.execute(
                text("""
                INSERT INTO app.turns
                    (session_id, turn_no, stage_index, question, answer, answered_at)
                SELECT :id, n, 0, '受控问题 ' || n, '继续回答 第' || n || '题', now()
                FROM generate_series(2, 100) AS n
            """),
                {"id": session_id},
            )

        async def selected(_db, _limit=20):
            return [{"id": session_id, "user_id": USER_ID}]

        monkeypatch.setattr(worker, "recoverable_sessions", selected)
        monkeypatch.setattr(worker, "get_model_adapter", lambda: model)
        monkeypatch.setattr(worker, "get_retriever", lambda: harness.retriever)
        assert await worker.recover_once() == 1
        current = await harness.client.get(f"{base}/current", headers=HEADERS)
        assert current.status_code == 200
        assert current.json()["session"]["status"] == "completed"
        assert current.json()["session"]["termination_reason"] == "safety_cap"
        assert current.json()["current_turn"]["turn_no"] == 100
        async with engine.connect() as connection:
            count = await connection.scalar(
                text("SELECT count(*) FROM app.turns WHERE session_id = :id"), {"id": session_id}
            )
            assert count == 100
