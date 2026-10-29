"""Saver-specific recovery: interrupt persistence across saver rebuilds and cleanup."""

import json

import pytest
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from sqlalchemy import text
from test_gate4_interview import HEADERS, USER_ID, Harness, ScriptedModel
from test_gate5_basic import PostModel
from test_gate5_regression import completed_stage

from app.db import engine
from app.services import finalization
from app.services import interview as service
from app.services import interview_worker as worker
from app.services.interview_checkpoint import (
    FINALIZATION_NAMESPACE,
    INTERVIEW_NAMESPACE,
    delete_checkpoint,
    graph_config,
)
from app.settings import get_settings


async def saver_values(session_id, namespace: str) -> dict | None:
    """Read persisted channel values through a brand-new saver instance (simulated restart)."""
    config = graph_config(session_id, namespace)
    async with AsyncRedisSaver.from_conn_string(get_settings().redis_url) as saver:
        checkpoint = await saver.aget(config)
    values = checkpoint.get("channel_values") if checkpoint else None
    return dict(values) if isinstance(values, dict) else None


async def append_count(session_id) -> int:
    async with engine.connect() as connection:
        return await connection.scalar(
            text("SELECT count(*) FROM app.snapshot_append_operations WHERE session_id = :id"),
            {"id": session_id},
        )


@pytest.mark.asyncio
async def test_answer_interrupt_persists_across_saver_rebuild():
    model = ScriptedModel()
    async with Harness(model) as harness:
        session_id, base, started = await harness.create()
        assert started["awaiting"] == "answer"
        values = await saver_values(session_id, INTERVIEW_NAMESPACE)
        assert values is not None
        assert values["awaiting"] == "answer"
        assert service._state_trigger(values["trigger"]).next_turn_no == 1
        raw = "继续回答 secret=abcdefghijk"
        answered = await harness.answer(base, 1, raw)
        assert answered.status_code == 200, answered.text
        assert answered.json()["current_turn"]["turn_no"] == 2
        values = await saver_values(session_id, INTERVIEW_NAMESPACE)
        assert values["awaiting"] == "answer"
        assert service._state_trigger(values["trigger"]).next_turn_no == 2
        assert "abcdefghijk" not in json.dumps(values, ensure_ascii=False, default=str)
        async with engine.connect() as connection:
            stored = await connection.scalar(
                text("SELECT answer FROM app.turns WHERE session_id = :id AND turn_no = 1"),
                {"id": session_id},
            )
        assert stored == raw


@pytest.mark.asyncio
async def test_snapshot_confirmation_interrupt_persists_across_saver_rebuild():
    model = ScriptedModel()
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()
        pending = await harness.answer(base, 1, "纠正项目事实")
        assert pending.json()["awaiting"] == "snapshot_confirmation"
        values = await saver_values(session_id, INTERVIEW_NAMESPACE)
        assert values["awaiting"] == "snapshot_confirmation"
        assert values["pending_correction"] == "缓存层使用 Redis"
        assert values["decision"]["question"]
        assert service._state_trigger(values["trigger"]).answered_turn_no == 1
        # PostgreSQL facts while the interrupt is live: no append, turn still unanswered.
        assert await append_count(session_id) == 0
        before = model.supervisor_calls
        resolved = await harness.client.post(
            f"{base}/snapshot-corrections:resolve",
            headers=HEADERS,
            json={"turn_no": 1, "decision": "do_not_write"},
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["awaiting"] == "answer"
        assert resolved.json()["current_turn"]["turn_no"] == 2
        assert model.supervisor_calls == before
        assert await append_count(session_id) == 0


@pytest.mark.asyncio
async def test_decision_retry_interrupt_persists_across_saver_rebuild():
    model = ScriptedModel()
    model.fail_answer_once = True
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()
        failed = await harness.answer(base, 1, "继续回答")
        assert failed.status_code == 200, failed.text
        assert failed.json()["awaiting"] == "decision_retry"
        values = await saver_values(session_id, INTERVIEW_NAMESPACE)
        assert values["awaiting"] == "decision_retry"
        assert values["last_error_code"] == "provider_transport"
        before = model.supervisor_calls
        replay = await harness.answer(base, 1, "继续回答")
        assert replay.status_code == 200
        assert replay.json()["awaiting"] == "decision_retry"
        assert model.supervisor_calls == before
        recovered = await harness.client.post(f"{base}/decision:retry", headers=HEADERS)
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["current_turn"]["turn_no"] == 2
        assert model.supervisor_calls == before + 1
        values = await saver_values(session_id, INTERVIEW_NAMESPACE)
        assert values["awaiting"] == "answer"


@pytest.mark.asyncio
async def test_explicit_retry_rebuilds_owed_decision_after_checkpoint_loss():
    model = ScriptedModel()
    model.fail_answer_once = True
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()
        failed = await harness.answer(base, 1, "继续回答")
        assert failed.json()["awaiting"] == "decision_retry"
        await delete_checkpoint(session_id)
        assert await saver_values(session_id, INTERVIEW_NAMESPACE) is None
        before = model.supervisor_calls
        retried = await harness.client.post(f"{base}/decision:retry", headers=HEADERS)
        assert retried.status_code == 200, retried.text
        assert retried.json()["current_turn"]["turn_no"] == 2
        assert retried.json()["awaiting"] == "answer"
        assert model.supervisor_calls == before + 1
        await delete_checkpoint(session_id)
        unavailable = await harness.client.post(f"{base}/decision:retry", headers=HEADERS)
        assert unavailable.status_code == 409
        assert unavailable.json()["error"]["code"] == "retry_not_available"


@pytest.mark.asyncio
async def test_recorded_resume_keeps_committed_confirm_intent(monkeypatch):
    """A crashed confirm commits the append; a changed replay cannot un-write it."""
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
        values = await saver_values(session_id, INTERVIEW_NAMESPACE)
        assert values["awaiting"] == "snapshot_confirmation"
        assert await append_count(session_id) == 1
        before = model.supervisor_calls
        replayed = await harness.client.post(
            f"{base}/snapshot-corrections:resolve",
            headers=HEADERS,
            json={"turn_no": 1, "decision": "do_not_write"},
        )
        assert replayed.status_code == 200, replayed.text
        assert replayed.json()["awaiting"] == "answer"
        assert replayed.json()["current_turn"]["turn_no"] == 2
        assert model.supervisor_calls == before
        assert await append_count(session_id) == 1
        snapshot = await harness.client.get(f"{base}/snapshot.md", headers=HEADERS)
        assert snapshot.text.count("缓存层使用 Redis") == 1
        late_replay = await harness.client.post(
            f"{base}/snapshot-corrections:resolve",
            headers=HEADERS,
            json={"turn_no": 1, "decision": "confirm"},
        )
        assert late_replay.status_code == 409
        assert late_replay.json()["error"]["code"] == "operation_in_progress"


@pytest.mark.asyncio
async def test_recovery_rescan_after_crash_is_idempotent(monkeypatch):
    """Conditional publication keeps one turn even under repeated worker scans."""
    model = ScriptedModel()
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()
        original_publish = service._publish_decision

        async def crash_once(*args, **kwargs):
            monkeypatch.setattr(service, "_publish_decision", original_publish)
            raise RuntimeError("simulated process stop after Supervisor returned")

        monkeypatch.setattr(service, "_publish_decision", crash_once)
        interrupted = await harness.answer(base, 1, "继续回答")
        assert interrupted.status_code == 500

        async def selected(_db, _limit=20):
            return [{"id": session_id, "user_id": USER_ID}]

        monkeypatch.setattr(worker, "recoverable_sessions", selected)
        monkeypatch.setattr(worker, "get_model_adapter", lambda: model)
        monkeypatch.setattr(worker, "get_retriever", lambda: harness.retriever)
        assert await worker.recover_once() == 1
        current = await harness.client.get(f"{base}/current", headers=HEADERS)
        assert current.json()["current_turn"]["turn_no"] == 2
        # The recovered run persisted its own answer interrupt for the new question.
        values = await saver_values(session_id, INTERVIEW_NAMESPACE)
        assert values is not None
        assert values["awaiting"] == "answer"
        before = model.supervisor_calls
        assert await worker.recover_once() == 1
        assert model.supervisor_calls == before
        replay = await harness.answer(base, 1, "继续回答")
        assert replay.status_code == 200
        assert replay.json()["current_turn"]["turn_no"] == 2
        assert model.supervisor_calls == before
        async with engine.connect() as connection:
            count = await connection.scalar(
                text("SELECT count(*) FROM app.turns WHERE session_id = :id"), {"id": session_id}
            )
        assert count == 2


@pytest.mark.asyncio
async def test_terminal_cleanup_removes_both_graph_threads_idempotently():
    model = PostModel()
    async with Harness(model) as harness:
        session_id, base = await completed_stage(harness)
        await finalization.run_finalization(session_id, model)
        result = (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()
        assert result["session"]["status"] == "completed"
        assert result["report"] is not None
        assert await saver_values(session_id, INTERVIEW_NAMESPACE) is None
        assert await saver_values(session_id, FINALIZATION_NAMESPACE) is None
        await delete_checkpoint(session_id)
        await delete_checkpoint(session_id)
        assert await saver_values(session_id, INTERVIEW_NAMESPACE) is None
        assert await saver_values(session_id, FINALIZATION_NAMESPACE) is None


@pytest.mark.asyncio
async def test_forced_exit_removes_interview_thread():
    model = ScriptedModel()
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()
        assert await saver_values(session_id, INTERVIEW_NAMESPACE) is not None
        aborted = await harness.client.post(f"{base}/force-exit:confirm", headers=HEADERS)
        assert aborted.status_code == 200, aborted.text
        assert aborted.json()["status"] == "aborted"
        assert await saver_values(session_id, INTERVIEW_NAMESPACE) is None
        await delete_checkpoint(session_id)
        assert await saver_values(session_id, INTERVIEW_NAMESPACE) is None
