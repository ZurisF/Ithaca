"""Small Gate 5 public-path smoke checks; full fault-window tests run separately."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_gate4_interview import HEADERS, Harness, ScriptedModel

from app.bank.retrieval import QuestionCandidate
from app.db import engine
from app.services.finalization import run_finalization, settle


class PostModel(ScriptedModel):
    def __init__(self):
        super().__init__()
        self.report_payload = None

    async def generate_structured(self, **kwargs):
        operation = kwargs["operation"]
        if operation == "project_answers":
            return kwargs["output_schema"](
                post_verification_append=None,
                answers=[{"turn_no": 1, "project_answer": "项目使用检索。"}],
            )
        if operation == "ideal_answer":
            return kwargs["output_schema"](ideal_answer="解释召回与排序。")
        if operation == "evaluation":
            return kwargs["output_schema"](comment="回答解释了关键步骤。")
        if operation == "report":
            self.report_payload = json.loads(kwargs["messages"][1].content)
            assert "project_answer" not in kwargs["messages"][1].content
            assert "ideal_answer" not in kwargs["messages"][1].content
            return kwargs["output_schema"](
                overall="总体表现清晰。",
                dimensions={
                    key: {"score": 0, "analysis": "没有足够信息做出有效评价。"}
                    for key in (
                        "requirements_understanding",
                        "system_design",
                        "technical_depth",
                        "engineering_quality",
                        "failure_thinking",
                        "data_awareness",
                        "communication_structure",
                        "retrospection",
                    )
                },
                project_recommendations="补充链路证据。",
                training_recommendations="练习检索设计。",
            )
        return await super().generate_structured(**kwargs)


class BankRetriever:
    def __init__(self, first, second):
        self.candidates = [
            QuestionCandidate(first, "阶段 0 的首题？"),
            QuestionCandidate(second, "阶段 1 的首题？"),
        ]

    async def retrieve_for_turn(self, *_args, **_kwargs):
        return self.candidates


@pytest.mark.asyncio
async def test_finish_early_finalization_and_exports():
    model = PostModel()
    first, second = uuid4(), uuid4()
    async with engine.begin() as connection:
        for question_id, question in ((first, "阶段 0 的首题？"), (second, "阶段 1 的首题？")):
            await connection.execute(
                text(
                    "INSERT INTO bank.questions (id, question, topic_path) VALUES (:id, :q, 'rag')"
                ),
                {"id": question_id, "q": question},
            )
    try:
        async with Harness(model) as harness:
            harness.retriever = BankRetriever(first, second)
            session_id, base, _ = await harness.create()
            assert (await harness.answer(base, 1, "结束阶段")).status_code == 200
            feedback = await harness.client.put(
                f"{base}/turns/1/feedback",
                headers=HEADERS,
                json={"value": "downvote", "reason": "表述不清"},
            )
            assert feedback.status_code == 200, feedback.text
            ended = await harness.client.post(f"{base}/finish-early", headers=HEADERS)
            assert ended.status_code == 200, ended.text
            assert ended.json()["status"] == "post_processing"
            frozen = await harness.client.put(
                f"{base}/turns/1/feedback",
                headers=HEADERS,
                json={"value": "upvote"},
            )
            assert frozen.status_code == 409
            await run_finalization(session_id, model)
            await settle(session_id)
            result = await harness.client.get(f"{base}/full-qa", headers=HEADERS)
            assert result.status_code == 200, result.text
            data = result.json()
            assert data["session"]["status"] == "completed"
            assert data["turns"][0]["comment"] == "回答解释了关键步骤。"
            assert data["turns"][1]["answer"] is None
            assert data["turns"][1]["comment"] is None
            assert model.report_payload is not None
            for path in ("snapshot.md", "full-qa.md", "report.md"):
                export = await harness.client.get(f"{base}/{path}", headers=HEADERS)
                assert export.status_code == 200, export.text
                assert export.text
            report_md = await harness.client.get(f"{base}/report.md", headers=HEADERS)
            assert "0..5" not in report_md.text
            async with engine.connect() as connection:
                count = await connection.scalar(
                    text("SELECT count(*) FROM bank.session_settlements WHERE session_id = :id"),
                    {"id": session_id},
                )
                assert count == 1
                counters = (
                    await connection.execute(
                        text(
                            "SELECT id, usage_count, downvote_count FROM bank.questions WHERE id IN (:first, :second)"
                        ),
                        {"first": first, "second": second},
                    )
                ).all()
                assert {row[0]: (row[1], row[2]) for row in counters} == {
                    first: (1, 1),
                    second: (1, 0),
                }
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM bank.questions WHERE id IN (:first, :second)"),
                {"first": first, "second": second},
            )


@pytest.mark.asyncio
async def test_force_exit_settles_without_post_tasks():
    model = PostModel()
    async with Harness(model) as harness:
        session_id, base, _ = await harness.create()
        ended = await harness.client.post(f"{base}/force-exit:confirm", headers=HEADERS)
        assert ended.status_code == 200, ended.text
        assert ended.json()["status"] == "aborted"
        await settle(session_id)
        result = await harness.client.get(f"{base}/full-qa", headers=HEADERS)
        assert result.json()["report"] is None
        async with engine.connect() as connection:
            count = await connection.scalar(
                text("SELECT count(*) FROM app.post_tasks WHERE session_id = :id"),
                {"id": session_id},
            )
            assert count == 0
