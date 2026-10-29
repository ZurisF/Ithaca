"""Gate 5 regression windows against real PostgreSQL and Redis."""

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langgraph.errors import NodeCancelledError
from sqlalchemy import text
from test_gate4_interview import HEADERS, BlockingModel, Harness
from test_gate5_basic import PostModel

from app.db import engine
from app.domain.contracts import ResultView
from app.services import finalization, interview_worker
from app.services.interview_checkpoint import delete_checkpoint, read_finalization_checkpoint
from app.services.result_render import render_full_qa_markdown, render_report_markdown


async def completed_stage(harness: Harness) -> tuple:
    session_id, base, _ = await harness.create()
    first = await harness.answer(base, 1, "先解释召回")
    assert first.status_code == 200, first.text
    second = await harness.answer(base, 2, "结束阶段")
    assert second.status_code == 200, second.text
    ended = await harness.client.post(f"{base}/finish-early", headers=HEADERS)
    assert ended.status_code == 200, ended.text
    assert ended.json()["status"] == "post_processing"
    return session_id, base


@pytest.mark.asyncio
async def test_normal_final_stage_closure_enters_post_processing_and_completes():
    model = PostModel()
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()
        for turn_no in range(1, 6):
            response = await harness.answer(base, turn_no, "结束阶段")
            assert response.status_code == 200, response.text
        current = (await harness.client.get(f"{base}/current", headers=HEADERS)).json()
        assert current["session"]["status"] == "post_processing"
        assert current["session"]["termination_reason"] == "normal"
        assert current["current_turn"]["turn_no"] == 5
        await finalization.run_finalization(session_id, model)
        result = (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()
        assert result["session"]["status"] == "completed"
        assert len(result["turns"]) == 5
        assert all(turn["answer"] is not None and turn["comment"] for turn in result["turns"])
        assert result["report"] is not None


class CapturingPostModel(PostModel):
    def __init__(
        self, *, fail_project=False, fail_ideal=False, fail_evaluation=False, fail_report=False
    ):
        super().__init__()
        self.fail_project = fail_project
        self.fail_ideal = fail_ideal
        self.fail_evaluation = fail_evaluation
        self.fail_report = fail_report
        self.inputs = []

    async def generate_structured(self, **kwargs):
        operation = kwargs["operation"]
        if operation in {"project_answers", "ideal_answer", "evaluation", "report"}:
            payload = json.loads(kwargs["messages"][1].content)
            self.inputs.append((operation, payload))
            if operation == "project_answers" and self.fail_project:
                raise RuntimeError("controlled project answer failure")
            if operation == "project_answers":
                return kwargs["output_schema"](
                    post_verification_append=None,
                    answers=[{"turn_no": 1, "project_answer": "项目采用两路召回。"}],
                )
            if (
                operation == "ideal_answer"
                and self.fail_ideal
                and "后续问题" in payload["question"]
            ):
                raise RuntimeError("controlled ideal answer failure")
            if (
                operation == "evaluation"
                and self.fail_evaluation
                and "后续问题" in payload["question"]
            ):
                raise RuntimeError("controlled evaluation failure")
            if operation == "report" and self.fail_report:
                raise RuntimeError("controlled report failure")
        return await super().generate_structured(**kwargs)


class VerifiedProjectModel(CapturingPostModel):
    async def generate_structured(self, **kwargs):
        if kwargs["operation"] == "project_answers":
            self.inputs.append(("project_answers", json.loads(kwargs["messages"][1].content)))
            return kwargs["output_schema"](
                post_verification_append="目录核验确认检索结果经过 RRF 融合。",
                answers=[
                    {"turn_no": 1, "project_answer": "不应采用的重复项 A"},
                    {"turn_no": 1, "project_answer": "不应采用的重复项 B"},
                    {"turn_no": 2, "project_answer": "采用 RRF 融合检索结果。"},
                    {"turn_no": 3, "project_answer": "未答题不应采用"},
                    {"turn_no": 99, "project_answer": "不存在的题号"},
                    {"turn_no": "bad", "project_answer": "非法题号"},
                ],
            )
        return await super().generate_structured(**kwargs)


@pytest.mark.asyncio
async def test_crash_during_post_verification_transaction_recovers_once():
    model = VerifiedProjectModel()
    async with Harness(model) as harness:
        session_id, base = await completed_stage(harness)
        suffix = uuid4().hex
        function_name = f"gate5_pause_{suffix}"
        trigger_name = f"gate5_pause_{suffix}"
        async with engine.begin() as connection:
            await connection.execute(
                text(f"""
                CREATE FUNCTION app.{function_name}() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.session_id = '{session_id}'::uuid THEN
                        PERFORM pg_sleep(20);
                    END IF;
                    RETURN NEW;
                END; $$
            """)
            )
            await connection.execute(
                text(f"""
                CREATE TRIGGER {trigger_name} BEFORE INSERT
                ON app.snapshot_append_operations FOR EACH ROW
                EXECUTE FUNCTION app.{function_name}()
            """)
            )
        running = asyncio.create_task(finalization.run_finalization(session_id, model))
        try:

            async def wait_for_pause():
                while True:
                    async with engine.connect() as connection:
                        paused = await connection.scalar(
                            text("""
                            SELECT count(*) FROM pg_stat_activity
                            WHERE wait_event = 'PgSleep'
                              AND query LIKE '%INSERT INTO app.snapshot_append_operations%'
                              AND pid <> pg_backend_pid()
                        """)
                        )
                    if paused:
                        return
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(wait_for_pause(), 5)
            running.cancel()
            with pytest.raises((asyncio.CancelledError, NodeCancelledError)):
                await asyncio.wait_for(running, 5)
        finally:
            if not running.done():
                running.cancel()
                try:
                    await running
                except (asyncio.CancelledError, NodeCancelledError):
                    pass
            async with engine.begin() as connection:
                await connection.execute(
                    text(f"DROP TRIGGER IF EXISTS {trigger_name} ON app.snapshot_append_operations")
                )
                await connection.execute(text(f"DROP FUNCTION IF EXISTS app.{function_name}()"))
        async with engine.begin() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM app.snapshot_append_operations WHERE session_id = :id"
                    ),
                    {"id": session_id},
                )
                == 0
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM app.turn_post_results "
                        "WHERE session_id = :id AND project_answer IS NOT NULL"
                    ),
                    {"id": session_id},
                )
                == 0
            )
            await connection.execute(
                text(
                    "UPDATE app.post_tasks SET lease_expires_at = now() - interval '1 second' "
                    "WHERE session_id = :id AND status = 'running'"
                ),
                {"id": session_id},
            )
        await finalization.run_finalization(session_id, model)
        result = (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()
        snapshot = (await harness.client.get(f"{base}/snapshot.md", headers=HEADERS)).text
        assert result["session"]["status"] == "completed"
        assert result["turns"][1]["project_answer"] == "采用 RRF 融合检索结果。"
        assert snapshot.count("目录核验确认检索结果经过 RRF 融合。") == 1
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM app.snapshot_append_operations WHERE session_id = :id"
                    ),
                    {"id": session_id},
                )
                == 1
            )


@pytest.mark.asyncio
async def test_project_items_post_verification_barrier_and_exact_exports():
    model = VerifiedProjectModel()
    async with Harness(model) as harness:
        session_id, base = await completed_stage(harness)
        await finalization.run_finalization(session_id, model)
        response = await harness.client.get(f"{base}/full-qa", headers=HEADERS)
        assert response.status_code == 200
        result = ResultView.model_validate(response.json())
        assert result.turns[0].project_answer is None
        assert result.turns[1].project_answer == "采用 RRF 融合检索结果。"
        assert result.turns[2].project_answer is None
        snapshot = await harness.client.get(f"{base}/snapshot.md", headers=HEADERS)
        full_qa = await harness.client.get(f"{base}/full-qa.md", headers=HEADERS)
        report = await harness.client.get(f"{base}/report.md", headers=HEADERS)
        assert snapshot.status_code == full_qa.status_code == report.status_code == 200
        assert snapshot.text.count("目录核验确认检索结果经过 RRF 融合。") == 1
        assert full_qa.text == render_full_qa_markdown(result)
        assert report.text == render_report_markdown(result.report)
        assert "第 3 题" in full_qa.text and "未回答" in full_qa.text
        assert "0..5" not in report.text and "证据不足（0）" not in report.text
        for operation, payload in model.inputs:
            if operation in {"evaluation", "report"}:
                assert payload["snapshot"] == snapshot.text
        async with engine.connect() as connection:
            receipt = await connection.scalar(
                text(
                    "SELECT count(*) FROM app.snapshot_append_operations "
                    "WHERE session_id = :id AND section = '事后核验'"
                ),
                {"id": session_id},
            )
            task = (
                await connection.execute(
                    text(
                        "SELECT status FROM app.post_tasks WHERE session_id = :id AND kind = 'project_answers'"
                    ),
                    {"id": session_id},
                )
            ).scalar_one()
        assert receipt == 1
        assert task == "succeeded"


@pytest.mark.asyncio
async def test_reference_failure_is_nullable_and_report_input_is_isolated():
    model = CapturingPostModel(fail_ideal=True)
    async with Harness(model) as harness:
        session_id, base = await completed_stage(harness)
        await finalization.run_finalization(session_id, model)
        result = (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()
        assert result["session"]["status"] == "completed"
        assert result["report"] is not None
        assert result["processing_incomplete"] is False
        assert result["turns"][0]["project_answer"] == "项目采用两路召回。"
        assert result["turns"][1]["project_answer"] is None
        assert result["turns"][1]["ideal_answer"] is None
        assert all(turn["comment"] for turn in result["turns"][:2])
        assert result["turns"][2]["answer"] is None
        assert result["turns"][2]["comment"] is None
        assert len([item for item in model.inputs if item[0] == "evaluation"]) == 2
        assert len([item for item in model.inputs if item[0] == "ideal_answer"]) == 2
        for operation, payload in model.inputs:
            assert "feedback" not in json.dumps(payload)
            if operation == "ideal_answer":
                assert set(payload) == {"question"}
            if operation == "evaluation":
                assert set(payload) == {
                    "snapshot",
                    "question",
                    "answer",
                    "project_answer",
                    "ideal_answer",
                }
            if operation == "report":
                assert set(payload) == {"snapshot", "turns"}
                assert len(payload["turns"]) == 2
                assert all(
                    set(turn) == {"stage", "question", "answer", "comment"}
                    for turn in payload["turns"]
                )
        async with engine.connect() as connection:
            tasks = (
                await connection.execute(
                    text("SELECT kind, turn_no, status FROM app.post_tasks WHERE session_id = :id"),
                    {"id": session_id},
                )
            ).all()
        assert ("ideal_answer", 2, "failed") in tasks
        assert ("report", None, "succeeded") in tasks


@pytest.mark.asyncio
async def test_failed_evaluation_prevents_report_but_preserves_sibling_comment():
    model = CapturingPostModel(fail_evaluation=True)
    async with Harness(model) as harness:
        session_id, base = await completed_stage(harness)
        await finalization.run_finalization(session_id, model)
        result = (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()
        assert result["session"]["status"] == "completed"
        assert result["processing_incomplete"] is True
        assert result["report"] is None
        assert result["turns"][0]["comment"]
        assert result["turns"][1]["comment"] is None
        assert not any(operation == "report" for operation, _ in model.inputs)
        assert (await harness.client.get(f"{base}/report", headers=HEADERS)).status_code == 404
        async with engine.connect() as connection:
            tasks = (
                await connection.execute(
                    text("SELECT kind, turn_no, status FROM app.post_tasks WHERE session_id = :id"),
                    {"id": session_id},
                )
            ).all()
        assert ("evaluation", 2, "failed") in tasks
        assert not any(kind == "report" for kind, _, _ in tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["project", "report"])
async def test_project_or_report_failure_keeps_available_results(failure):
    model = CapturingPostModel(fail_project=failure == "project", fail_report=failure == "report")
    async with Harness(model) as harness:
        session_id, base = await completed_stage(harness)
        await finalization.run_finalization(session_id, model)
        result = (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()
        assert result["session"]["status"] == "completed"
        assert all(turn["comment"] for turn in result["turns"][:2])
        assert all(turn["ideal_answer"] for turn in result["turns"][:2])
        if failure == "project":
            assert all(turn["project_answer"] is None for turn in result["turns"])
            assert result["report"] is not None
            assert result["processing_incomplete"] is False
        else:
            assert result["turns"][0]["project_answer"]
            assert result["report"] is None
            assert result["processing_incomplete"] is True
            assert (
                await harness.client.get(f"{base}/report.md", headers=HEADERS)
            ).status_code == 404
        async with engine.connect() as connection:
            failed = (
                (
                    await connection.execute(
                        text(
                            "SELECT kind FROM app.post_tasks WHERE session_id = :id AND status = 'failed'"
                        ),
                        {"id": session_id},
                    )
                )
                .scalars()
                .all()
            )
        assert failed == ["project_answers" if failure == "project" else "report"]


@pytest.mark.asyncio
async def test_settlement_rollback_ack_loss_and_concurrent_replay():
    model = PostModel()
    question_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO bank.questions (id, question, topic_path) VALUES (:id, '阶段 0 的首题？', 'rag')"
            ),
            {"id": question_id},
        )
    try:
        async with Harness(model) as harness:
            from test_gate5_basic import BankRetriever

            harness.retriever = BankRetriever(question_id, uuid4())
            session_id, base, _ = await harness.create()
            assert (
                await harness.client.put(
                    f"{base}/turns/1/feedback",
                    headers=HEADERS,
                    json={"value": "downvote", "reason": "不相关"},
                )
            ).status_code == 200
            assert (
                await harness.client.post(f"{base}/force-exit:confirm", headers=HEADERS)
            ).status_code == 200
            suffix = uuid4().hex
            function_name = f"gate5_settle_fail_{suffix}"
            trigger_name = f"gate5_settle_fail_{suffix}"
            async with engine.begin() as connection:
                await connection.execute(
                    text(f"""
                    CREATE FUNCTION bank.{function_name}() RETURNS trigger LANGUAGE plpgsql AS $$
                    BEGIN
                        IF NEW.id = '{question_id}'::uuid THEN
                            RAISE EXCEPTION 'controlled settlement update failure';
                        END IF;
                        RETURN NEW;
                    END; $$
                """)
                )
                await connection.execute(
                    text(f"""
                    CREATE TRIGGER {trigger_name} BEFORE UPDATE ON bank.questions
                    FOR EACH ROW EXECUTE FUNCTION bank.{function_name}()
                """)
                )
            try:
                with pytest.raises(Exception, match="controlled settlement update failure"):
                    await finalization.settle(session_id)
            finally:
                async with engine.begin() as connection:
                    await connection.execute(
                        text(f"DROP TRIGGER IF EXISTS {trigger_name} ON bank.questions")
                    )
                    await connection.execute(
                        text(f"DROP FUNCTION IF EXISTS bank.{function_name}()")
                    )
            async with engine.connect() as connection:
                counts = (
                    await connection.execute(
                        text(
                            "SELECT usage_count, downvote_count FROM bank.questions WHERE id = :id"
                        ),
                        {"id": question_id},
                    )
                ).one()
                marker = await connection.scalar(
                    text("SELECT count(*) FROM bank.session_settlements WHERE session_id = :id"),
                    {"id": session_id},
                )
            assert counts == (0, 0)
            assert marker == 0
            await asyncio.gather(finalization.settle(session_id), finalization.settle(session_id))
            await finalization.settle(session_id)  # committed transaction, lost acknowledgement
            async with engine.connect() as connection:
                counts = (
                    await connection.execute(
                        text(
                            "SELECT usage_count, downvote_count FROM bank.questions WHERE id = :id"
                        ),
                        {"id": question_id},
                    )
                ).one()
                marker = await connection.scalar(
                    text("SELECT count(*) FROM bank.session_settlements WHERE session_id = :id"),
                    {"id": session_id},
                )
            assert counts == (1, 1)
            assert marker == 1
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM bank.questions WHERE id = :id"), {"id": question_id}
            )


async def wait_for_session_lock_waiters(count: int) -> None:
    async def waiting() -> None:
        while True:
            async with engine.connect() as connection:
                current = await connection.scalar(
                    text("""
                    SELECT count(*) FROM pg_stat_activity
                    WHERE wait_event_type = 'Lock'
                      AND query LIKE '%app.interview_sessions s%'
                      AND pid <> pg_backend_pid()
                """)
                )
            if current >= count:
                return
            await asyncio.sleep(0.01)

    await asyncio.wait_for(waiting(), timeout=5)


@pytest.mark.asyncio
@pytest.mark.parametrize("first_command", ["feedback", "terminate"])
async def test_feedback_put_and_terminal_freeze_follow_session_lock_order(first_command):
    model = PostModel()
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()

        async def feedback():
            return await harness.client.put(
                f"{base}/turns/1/feedback",
                headers=HEADERS,
                json={"value": "downvote", "reason": "重复"},
            )

        async def terminate():
            return await harness.client.post(f"{base}/force-exit:confirm", headers=HEADERS)

        commands = {"feedback": feedback, "terminate": terminate}
        second_command = "terminate" if first_command == "feedback" else "feedback"
        async with engine.begin() as lock_connection:
            await lock_connection.execute(
                text("SELECT id FROM app.interview_sessions WHERE id = :id FOR UPDATE"),
                {"id": session_id},
            )
            first = asyncio.create_task(commands[first_command]())
            await wait_for_session_lock_waiters(1)
            second = asyncio.create_task(commands[second_command]())
            await wait_for_session_lock_waiters(2)
            assert not first.done() and not second.done()
        first_response, second_response = await asyncio.gather(first, second)
        responses = {first_command: first_response, second_command: second_response}
        await finalization.settle(session_id)
        result = (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()
        assert responses["terminate"].status_code == 200
        assert result["session"]["status"] == "aborted"
        if first_command == "feedback":
            assert responses["feedback"].status_code == 200
            assert result["turns"][0]["feedback"] == {"value": "downvote", "reason": "重复"}
        else:
            assert responses["feedback"].status_code == 409
            assert result["turns"][0]["feedback"] is None
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT count(*) FROM bank.session_settlements WHERE session_id = :id"),
                    {"id": session_id},
                )
                == 1
            )


class BlockedReferences(PostModel):
    def __init__(self):
        super().__init__()
        self.entered = {name: asyncio.Event() for name in ("project_answers", "ideal_answer")}
        self.release = asyncio.Event()

    async def generate_structured(self, **kwargs):
        if kwargs["operation"] in self.entered:
            self.entered[kwargs["operation"]].set()
            await self.release.wait()
        return await super().generate_structured(**kwargs)


async def wait_for_task_status(session_id, kind: str, expected: int) -> None:
    async def waiting() -> None:
        while True:
            async with engine.connect() as connection:
                count = await connection.scalar(
                    text("""
                    SELECT count(*) FROM app.post_tasks
                    WHERE session_id = :id AND kind = :kind AND status = 'succeeded'
                """),
                    {"id": session_id, "kind": kind},
                )
            if count == expected:
                return
            await asyncio.sleep(0.01)

    await asyncio.wait_for(waiting(), timeout=5)


class OrderedReferences(CapturingPostModel):
    def __init__(self, blocked: str):
        super().__init__()
        self.blocked = blocked
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def generate_structured(self, **kwargs):
        if kwargs["operation"] == self.blocked:
            self.entered.set()
            await self.release.wait()
        return await super().generate_structured(**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", ["ideal_answer", "project_answers"])
async def test_reference_completion_order_keeps_evaluation_behind_barrier(blocked):
    model = OrderedReferences(blocked)
    async with Harness(model) as harness:
        session_id, base = await completed_stage(harness)
        running = asyncio.create_task(finalization.run_finalization(session_id, model))
        try:
            await asyncio.wait_for(model.entered.wait(), 5)
            other = "project_answers" if blocked == "ideal_answer" else "ideal_answer"
            await wait_for_task_status(session_id, other, 1 if other == "project_answers" else 2)
            assert not any(operation == "evaluation" for operation, _ in model.inputs)
            async with engine.connect() as connection:
                evaluation_count = await connection.scalar(
                    text(
                        "SELECT count(*) FROM app.post_tasks WHERE session_id = :id AND kind = 'evaluation'"
                    ),
                    {"id": session_id},
                )
            assert evaluation_count == 0
        finally:
            model.release.set()
            await asyncio.wait_for(running, 5)
        result = (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()
        assert result["session"]["status"] == "completed"
        assert result["report"] is not None
        assert len([operation for operation, _ in model.inputs if operation == "evaluation"]) == 2


@pytest.mark.asyncio
async def test_force_exit_rejects_late_reference_results():
    model = BlockedReferences()
    async with Harness(model) as harness:
        session_id, base = await completed_stage(harness)
        running = asyncio.create_task(finalization.run_finalization(session_id, model))
        try:
            await asyncio.wait_for(
                asyncio.gather(*(event.wait() for event in model.entered.values())), 5
            )
            aborted = await harness.client.post(f"{base}/force-exit:confirm", headers=HEADERS)
            assert aborted.status_code == 200, aborted.text
            assert aborted.json()["status"] == "aborted"
        finally:
            model.release.set()
            await asyncio.wait_for(running, 5)
        result = (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()
        assert result["session"]["status"] == "aborted"
        assert result["report"] is None
        assert all(
            turn["project_answer"] is None and turn["ideal_answer"] is None
            for turn in result["turns"]
        )
        async with engine.connect() as connection:
            artifacts = await connection.scalar(
                text("SELECT count(*) FROM app.turn_post_results WHERE session_id = :id"),
                {"id": session_id},
            )
            tasks = await connection.scalar(
                text("SELECT count(*) FROM app.post_tasks WHERE session_id = :id"),
                {"id": session_id},
            )
        assert artifacts == tasks == 0


@pytest.mark.asyncio
async def test_force_exit_after_answer_commit_rejects_late_supervisor_decision():
    model = BlockingModel()
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()
        answering = asyncio.create_task(harness.answer(base, 1, "回答后等待模型"))
        try:
            await asyncio.wait_for(model.entered.wait(), 5)
            aborted = await harness.client.post(f"{base}/force-exit:confirm", headers=HEADERS)
            assert aborted.status_code == 200, aborted.text
            assert aborted.json()["status"] == "aborted"
        finally:
            model.release.set()
            await asyncio.wait_for(answering, 5)
        result = (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()
        assert result["session"]["status"] == "aborted"
        assert len(result["turns"]) == 1
        assert result["turns"][0]["answer"] == "回答后等待模型"
        async with engine.connect() as connection:
            stages = await connection.scalar(
                text("SELECT count(*) FROM app.stage_results WHERE session_id = :id"),
                {"id": session_id},
            )
        assert stages == 0


@pytest.mark.asyncio
async def test_force_exit_can_cancel_unpublished_post_processing_but_not_published_results():
    model = PostModel()
    async with Harness(model) as harness:
        session_id, base = await completed_stage(harness)
        aborted = await harness.client.post(f"{base}/force-exit:confirm", headers=HEADERS)
        assert aborted.status_code == 200
        assert aborted.json()["status"] == "aborted"
        await finalization.run_finalization(session_id, model)
        assert (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()[
            "report"
        ] is None
    ordered = OrderedReferences("ideal_answer")
    async with Harness(ordered) as harness:
        session_id, base = await completed_stage(harness)
        running = asyncio.create_task(finalization.run_finalization(session_id, ordered))
        try:
            await asyncio.wait_for(ordered.entered.wait(), 5)
            await wait_for_task_status(session_id, "project_answers", 1)
            rejected = await harness.client.post(f"{base}/force-exit:confirm", headers=HEADERS)
            assert rejected.status_code == 200
            assert rejected.json()["status"] == "post_processing"
        finally:
            ordered.release.set()
            await asyncio.wait_for(running, 5)
        result = (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()
        assert result["session"]["status"] == "completed"
        assert result["turns"][0]["project_answer"] is not None


class CrashingIdeal(PostModel):
    def __init__(self):
        super().__init__()
        self.crash_once = True
        self.calls = {"project_answers": 0, "ideal_answer": 0, "report": 0}

    async def generate_structured(self, **kwargs):
        operation = kwargs["operation"]
        if operation in self.calls:
            self.calls[operation] += 1
        if operation == "ideal_answer" and self.crash_once:
            self.crash_once = False
            raise asyncio.CancelledError("simulated worker crash after claim")
        return await super().generate_structured(**kwargs)


class CancelAfterModelResponse(PostModel):
    def __init__(self):
        super().__init__()
        self.cancel_once = True
        self.ideal_calls = 0

    async def generate_structured(self, **kwargs):
        result = await super().generate_structured(**kwargs)
        if kwargs["operation"] == "ideal_answer":
            self.ideal_calls += 1
            if self.cancel_once:
                self.cancel_once = False
                asyncio.current_task().cancel()
        return result


class BlockSecondIdeal(PostModel):
    def __init__(self):
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = []

    async def generate_structured(self, **kwargs):
        operation = kwargs["operation"]
        if operation in {"project_answers", "ideal_answer", "evaluation", "report"}:
            payload = json.loads(kwargs["messages"][1].content)
            self.calls.append((operation, payload))
            if operation == "ideal_answer" and "后续问题" in payload["question"]:
                self.entered.set()
                await self.release.wait()
        return await super().generate_structured(**kwargs)


@pytest.mark.asyncio
async def test_partial_fanout_restart_reuses_published_sibling_results():
    model = BlockSecondIdeal()
    async with Harness(model) as harness:
        session_id, base = await completed_stage(harness)
        running = asyncio.create_task(finalization.run_finalization(session_id, model))
        await asyncio.wait_for(model.entered.wait(), 5)
        await wait_for_task_status(session_id, "project_answers", 1)
        await wait_for_task_status(session_id, "ideal_answer", 1)
        running.cancel()
        with pytest.raises((asyncio.CancelledError, NodeCancelledError)):
            await asyncio.wait_for(running, 5)
        before = list(model.calls)
        model.release.set()
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "UPDATE app.post_tasks SET lease_expires_at = now() - interval '1 second' "
                    "WHERE session_id = :id AND status = 'running'"
                ),
                {"id": session_id},
            )
        await finalization.run_finalization(session_id, model)
        after = model.calls[len(before) :]
        assert not any(operation == "project_answers" for operation, _ in after)
        assert not any(
            operation == "ideal_answer" and "阶段 0 的首题" in payload["question"]
            for operation, payload in after
        )
        assert (
            len(
                [
                    1
                    for operation, payload in after
                    if operation == "ideal_answer" and "后续问题" in payload["question"]
                ]
            )
            == 1
        )
        result = (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()
        assert result["session"]["status"] == "completed"
        assert all(turn["ideal_answer"] for turn in result["turns"][:2])
        assert result["report"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("lose_checkpoint", [False, True])
async def test_finalization_redis_checkpoint_resumes_after_reference_barrier(
    monkeypatch, lose_checkpoint
):
    model = CapturingPostModel()
    entered = asyncio.Event()
    original_evaluation = finalization._evaluation

    async def paused_evaluation(*args):
        entered.set()
        await asyncio.Event().wait()

    async with Harness(model) as harness:
        session_id, base = await completed_stage(harness)
        monkeypatch.setattr(finalization, "_evaluation", paused_evaluation)
        running = asyncio.create_task(finalization.run_finalization(session_id, model))
        await asyncio.wait_for(entered.wait(), 10)
        assert await read_finalization_checkpoint(session_id) == "references_done"
        running.cancel()
        with pytest.raises((asyncio.CancelledError, NodeCancelledError)):
            await running

        prior_inputs = len(model.inputs)
        if lose_checkpoint:
            await delete_checkpoint(session_id)
            assert await read_finalization_checkpoint(session_id) is None
        else:

            async def references_must_be_skipped(*_args):
                raise AssertionError("reference node was re-entered after checkpoint")

            monkeypatch.setattr(finalization, "_project_answers", references_must_be_skipped)
        monkeypatch.setattr(finalization, "_evaluation", original_evaluation)
        await finalization.run_finalization(session_id, model)
        if lose_checkpoint:
            assert all(
                operation not in {"project_answers", "ideal_answer"}
                for operation, _ in model.inputs[prior_inputs:]
            )
        result = (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()
        assert result["session"]["status"] == "completed"
        assert result["report"] is not None
        assert await read_finalization_checkpoint(session_id) is None


@pytest.mark.asyncio
async def test_model_response_before_publication_can_resume_without_duplicate_artifact():
    model = CancelAfterModelResponse()
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()
        assert (await harness.answer(base, 1, "结束阶段")).status_code == 200
        assert (
            await harness.client.post(f"{base}/finish-early", headers=HEADERS)
        ).status_code == 200
        with pytest.raises(NodeCancelledError):
            await finalization.run_finalization(session_id, model)
        async with engine.begin() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM app.turn_post_results WHERE session_id = :id AND ideal_answer IS NOT NULL"
                    ),
                    {"id": session_id},
                )
                == 0
            )
            await connection.execute(
                text(
                    "UPDATE app.post_tasks SET lease_expires_at = now() - interval '1 second' "
                    "WHERE session_id = :id AND status = 'running'"
                ),
                {"id": session_id},
            )
        await finalization.run_finalization(session_id, model)
        result = (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()
        assert result["session"]["status"] == "completed"
        assert result["turns"][0]["ideal_answer"]
        assert model.ideal_calls == 2
        async with engine.connect() as connection:
            count = await connection.scalar(
                text("SELECT count(*) FROM app.turn_post_results WHERE session_id = :id"),
                {"id": session_id},
            )
        assert count == 1


@pytest.mark.asyncio
async def test_worker_scan_recovers_expired_post_task_lease(monkeypatch):
    model = PostModel()
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()
        assert (await harness.answer(base, 1, "结束阶段")).status_code == 200
        assert (
            await harness.client.post(f"{base}/finish-early", headers=HEADERS)
        ).status_code == 200
        task_key = f"{session_id}:ideal_answer:1"
        async with engine.begin() as connection:
            await connection.execute(
                text("""
                INSERT INTO app.post_tasks
                    (task_key, session_id, kind, turn_no, status, attempt_count,
                     lease_owner, lease_expires_at)
                VALUES (:key, :id, 'ideal_answer', 1, 'running', 1,
                        'crashed-worker', now() - interval '1 second')
            """),
                {"key": task_key, "id": session_id},
            )
        monkeypatch.setattr(
            interview_worker,
            "get_settings",
            lambda: SimpleNamespace(model_api_key="controlled", model_name="controlled"),
        )
        monkeypatch.setattr(interview_worker, "get_model_adapter", lambda: model)
        assert await interview_worker.recover_once() >= 1
        result = (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()
        assert result["session"]["status"] == "completed"
        assert result["report"] is not None
        async with engine.connect() as connection:
            task = (
                await connection.execute(
                    text("SELECT status, attempt_count FROM app.post_tasks WHERE task_key = :key"),
                    {"key": task_key},
                )
            ).one()
        assert task == ("succeeded", 2)


@pytest.mark.asyncio
async def test_expired_lease_resumes_and_report_ack_loss_is_idempotent():
    model = CrashingIdeal()
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()
        assert (await harness.answer(base, 1, "结束阶段")).status_code == 200
        assert (
            await harness.client.post(f"{base}/finish-early", headers=HEADERS)
        ).status_code == 200
        with pytest.raises(NodeCancelledError):
            await finalization.run_finalization(session_id, model)
        async with engine.begin() as connection:
            running = await connection.scalar(
                text(
                    "SELECT count(*) FROM app.post_tasks WHERE session_id = :id AND status = 'running'"
                ),
                {"id": session_id},
            )
            assert running >= 1
            await connection.execute(
                text(
                    "UPDATE app.post_tasks SET lease_expires_at = now() - interval '1 second' "
                    "WHERE session_id = :id AND status = 'running'"
                ),
                {"id": session_id},
            )
        await finalization.run_finalization(session_id, model)
        before = dict(model.calls)
        await finalization.run_finalization(session_id, model)
        assert model.calls == before
        result = (await harness.client.get(f"{base}/full-qa", headers=HEADERS)).json()
        assert result["session"]["status"] == "completed"
        assert result["report"] is not None
        async with engine.connect() as connection:
            report_count = await connection.scalar(
                text("SELECT count(*) FROM app.session_reports WHERE session_id = :id"),
                {"id": session_id},
            )
            task = (
                await connection.execute(
                    text(
                        "SELECT status, attempt_count FROM app.post_tasks WHERE session_id = :id "
                        "AND kind = 'ideal_answer'"
                    ),
                    {"id": session_id},
                )
            ).one()
        assert report_count == 1
        assert task == ("succeeded", 2)
