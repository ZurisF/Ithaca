"""Gate 7 public curation and deletion boundaries without post-processing workers."""

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text

from app.api.model_dependency import get_model_adapter
from app.bank.retrieval import get_retriever
from app.db import engine
from app.domain.contracts import CurationSuggestion
from app.main import app
from app.observability.trace import purge_expired_traces
from app.services import curation, session_deletion
from app.services import prepare as prepare_service

USER = UUID("00000000-0000-4000-8000-000000000001")
ADMIN = UUID("00000000-0000-4000-8000-000000000002")
USER_HEADERS = {"X-Dev-User": str(USER)}
ADMIN_HEADERS = {"X-Dev-User": str(ADMIN)}


class Embedder:
    async def embed_document(self, _question: str) -> list[float]:
        return [0.01] * 1024


class Retriever:
    models = Embedder()


async def fixture_session(session_id: UUID, *, granted: bool = False) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("""
            INSERT INTO app.interview_sessions
                (id, user_id, status, termination_reason, feedback_frozen_at,
                 completed_at, curation_review)
            VALUES (:id, :user, 'aborted', 'forced_exit', now(), now(), :granted)
        """),
            {"id": session_id, "user": USER, "granted": granted},
        )
        await connection.execute(
            text("""
            INSERT INTO app.turns (session_id, turn_no, stage_index, question, answer, answered_at)
            VALUES (:id, 1, 0, '项目专属问题？', '私人回答', now())
        """),
            {"id": session_id},
        )
        await connection.execute(
            text("""
            INSERT INTO bank.session_settlements (session_id) VALUES (:id)
        """),
            {"id": session_id},
        )


async def cleanup_session(session_id: UUID) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text("DELETE FROM app.interview_sessions WHERE id = :id"), {"id": session_id}
        )


@pytest.mark.asyncio
async def test_curation_grant_review_publish_revoke_and_private_read_boundary():
    session_id = uuid4()
    question = f"通用问题 {uuid4()}？"
    await fixture_session(session_id)
    app.dependency_overrides[get_retriever] = lambda: Retriever()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            path = f"/v1/interviews/{session_id}"
            queue = await client.get("/v1/admin/curation-items", headers=ADMIN_HEADERS)
            assert session_id not in {UUID(row["session_id"]) for row in queue.json()["sources"]}
            denied = await client.put(f"{path}/curation-grant", headers=ADMIN_HEADERS)
            assert denied.status_code == 403
            granted = await client.put(f"{path}/curation-grant", headers=USER_HEADERS)
            assert granted.status_code == 200 and granted.json()["curation_review"]
            queue = await client.get("/v1/admin/curation-items", headers=ADMIN_HEADERS)
            source = next(
                row for row in queue.json()["sources"] if row["session_id"] == str(session_id)
            )
            assert source["turns"][0]["answer"] == "私人回答"
            create = await client.post(
                "/v1/admin/curation-items",
                headers=ADMIN_HEADERS,
                json={"source_session_id": str(session_id), "source_turn_no": 1},
            )
            assert create.status_code == 200, create.text
            item_id = create.json()["id"]
            review = await client.post(
                "/v1/admin/curation-items",
                headers=ADMIN_HEADERS,
                json={
                    "source_session_id": str(session_id),
                    "source_turn_no": 1,
                    "item_id": item_id,
                    "status": "reviewed",
                    "edited_question": question,
                    "proposed_topic_path": "rag",
                    "review_notes": "已泛化项目名称与私有细节",
                },
            )
            assert review.status_code == 200, review.text
            assert not review.json()["exact_duplicate"]
            published = await client.post(
                f"/v1/admin/curation-items/{item_id}:add-to-question-bank",
                headers=ADMIN_HEADERS,
                json={"ideal_answer": "通用解答"},
            )
            assert published.status_code == 200, published.text
            assert published.json()["status"] == "added"
            revoked = await client.delete(f"{path}/curation-grant", headers=USER_HEADERS)
            assert revoked.status_code == 200 and not revoked.json()["curation_review"]
            queue = await client.get("/v1/admin/curation-items", headers=ADMIN_HEADERS)
            assert session_id not in {UUID(row["session_id"]) for row in queue.json()["sources"]}
            assert item_id not in {row["id"] for row in queue.json()["items"]}
            public = await client.get("/v1/admin/question-bank", headers=ADMIN_HEADERS)
            row = next(row for row in public.json() if row["question"] == question)
            assert "source_session_id" not in row and "私人回答" not in str(row)
            await client.delete(path, headers=USER_HEADERS)
            assert (await client.get(path, headers=USER_HEADERS)).status_code == 404
            public = await client.get("/v1/admin/question-bank", headers=ADMIN_HEADERS)
            assert any(row["question"] == question for row in public.json())
    finally:
        app.dependency_overrides.pop(get_retriever, None)
        await cleanup_session(session_id)
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM bank.questions WHERE question = :question"),
                {"question": question},
            )


@pytest.mark.asyncio
async def test_revoke_wins_during_embedding_and_delete_redis_failure_retains_locator(monkeypatch):
    session_id = uuid4()
    question = f"并发问题 {uuid4()}？"
    await fixture_session(session_id, granted=True)
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockedEmbedder:
        async def embed_document(self, _question: str) -> list[float]:
            entered.set()
            await release.wait()
            return [0.01] * 1024

    class BlockedRetriever:
        models = BlockedEmbedder()

    app.dependency_overrides[get_retriever] = lambda: BlockedRetriever()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            create = await client.post(
                "/v1/admin/curation-items",
                headers=ADMIN_HEADERS,
                json={"source_session_id": str(session_id), "source_turn_no": 1},
            )
            item_id = create.json()["id"]
            review = await client.post(
                "/v1/admin/curation-items",
                headers=ADMIN_HEADERS,
                json={
                    "source_session_id": str(session_id),
                    "source_turn_no": 1,
                    "item_id": item_id,
                    "status": "reviewed",
                    "edited_question": question,
                    "proposed_topic_path": "rag",
                    "review_notes": "已人工检查",
                },
            )
            assert review.status_code == 200
            pending = asyncio.create_task(
                client.post(
                    f"/v1/admin/curation-items/{item_id}:add-to-question-bank",
                    headers=ADMIN_HEADERS,
                    json={"ideal_answer": None},
                )
            )
            await asyncio.wait_for(entered.wait(), 5)
            revoked = await client.delete(
                f"/v1/interviews/{session_id}/curation-grant", headers=USER_HEADERS
            )
            assert revoked.status_code == 200
            release.set()
            published = await pending
            assert published.status_code == 404
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM bank.questions WHERE question = :q"),
                        {"q": question},
                    )
                    == 0
                )

            async def failed_cleanup(_session_id):
                raise RuntimeError("simulated Redis outage")

            original_cleanup = session_deletion.delete_checkpoint
            monkeypatch.setattr(session_deletion, "delete_checkpoint", failed_cleanup)
            deleted = await client.delete(f"/v1/interviews/{session_id}", headers=USER_HEADERS)
            assert deleted.status_code == 503 and deleted.json()["error"]["retryable"]
            assert (
                await client.get(f"/v1/interviews/{session_id}", headers=USER_HEADERS)
            ).status_code == 200
            monkeypatch.setattr(session_deletion, "delete_checkpoint", original_cleanup)
            retried = await client.delete(f"/v1/interviews/{session_id}", headers=USER_HEADERS)
            assert retried.status_code == 204
            assert (
                await client.get(f"/v1/interviews/{session_id}", headers=USER_HEADERS)
            ).status_code == 404
    finally:
        release.set()
        app.dependency_overrides.pop(get_retriever, None)
        await cleanup_session(session_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["interviewing", "completed"])
async def test_delete_active_or_completed_cascades_private_records_and_trace(status):
    session_id = uuid4()
    trace_id = uuid4()
    async with engine.begin() as connection:
        if status == "interviewing":
            await connection.execute(
                text("""
                INSERT INTO app.interview_sessions (id, user_id, status)
                VALUES (:id, :user, 'interviewing')
            """),
                {"id": session_id, "user": USER},
            )
        else:
            await connection.execute(
                text("""
                INSERT INTO app.interview_sessions
                    (id, user_id, status, termination_reason, feedback_frozen_at, completed_at)
                VALUES (:id, :user, 'completed', 'normal', now(), now())
            """),
                {"id": session_id, "user": USER},
            )
            await connection.execute(
                text("""
                INSERT INTO bank.session_settlements (session_id) VALUES (:id)
            """),
                {"id": session_id},
            )
        await connection.execute(
            text("""
            INSERT INTO app.session_snapshots (session_id, content) VALUES (:id, '# 私人项目')
        """),
            {"id": session_id},
        )
        await connection.execute(
            text("""
            INSERT INTO app.turns (session_id, turn_no, stage_index, question)
            VALUES (:id, 1, 0, '私人问题？')
        """),
            {"id": session_id},
        )
        await connection.execute(
            text("""
            INSERT INTO telemetry.model_calls
                (trace_id, session_id, operation_name, provider, model, status,
                 attempt_no, started_at, finished_at, latency_ms)
            VALUES (:trace, :id, 'test', 'test', 'test', 'succeeded', 1, now(), now(), 0)
        """),
            {"trace": trace_id, "id": session_id},
        )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            denied = await client.delete(f"/v1/interviews/{session_id}", headers=ADMIN_HEADERS)
            assert denied.status_code == 403
            deleted = await client.delete(f"/v1/interviews/{session_id}", headers=USER_HEADERS)
            assert deleted.status_code == 204, deleted.text
            assert (
                await client.get(f"/v1/interviews/{session_id}", headers=USER_HEADERS)
            ).status_code == 404
        async with engine.connect() as connection:
            for table, column in (
                ("app.interview_sessions", "id"),
                ("app.session_snapshots", "session_id"),
                ("app.turns", "session_id"),
                ("telemetry.model_calls", "session_id"),
                ("bank.session_settlements", "session_id"),
            ):
                assert (
                    await connection.scalar(
                        text(f"SELECT count(*) FROM {table} WHERE {column} = :id"),
                        {"id": session_id},
                    )
                    == 0
                )
    finally:
        await cleanup_session(session_id)


@pytest.mark.asyncio
async def test_agent_suggestion_is_only_a_draft(monkeypatch):
    session_id = uuid4()
    await fixture_session(session_id, granted=True)

    class SuggestingModel:
        async def generate_structured(self, **kwargs):
            assert kwargs["operation"] == "curation_suggestion"
            assert "私人回答" in kwargs["messages"][1].content
            return CurationSuggestion(
                edited_question="如何设计通用检索链路？",
                proposed_topic_path="rag",
                privacy_notes="已删除源项目标识，需人工复核。",
                duplicate_notes="需与相近检索题人工比较。",
                ideal_answer="说明召回、融合与排序。",
            )

    app.dependency_overrides[get_model_adapter] = SuggestingModel
    monkeypatch.setattr(
        curation,
        "get_settings",
        lambda: SimpleNamespace(
            model_api_key="configured",
            model_name="test",
            model_max_attempts=1,
            model_timeout_seconds=5,
        ),
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/v1/admin/curation-items",
                headers=ADMIN_HEADERS,
                json={"source_session_id": str(session_id), "source_turn_no": 1, "suggest": True},
            )
            assert response.status_code == 200, response.text
            assert response.json()["suggestion"]["proposed_topic_path"] == "rag"
            assert response.json()["status"] == "pending"
            queue = await client.get("/v1/admin/curation-items", headers=ADMIN_HEADERS)
            item = next(row for row in queue.json()["items"] if row["id"] == response.json()["id"])
            assert item["status"] == "pending" and item["suggestion"] is None
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT count(*) FROM bank.questions WHERE question = :q"),
                        {"q": "如何设计通用检索链路？"},
                    )
                    == 0
                )
    finally:
        app.dependency_overrides.pop(get_model_adapter, None)
        await cleanup_session(session_id)


@pytest.mark.asyncio
async def test_granted_active_session_is_not_administrator_material():
    session_id = uuid4()
    async with engine.begin() as connection:
        await connection.execute(
            text("""
                INSERT INTO app.interview_sessions (id, user_id, status, curation_review)
                VALUES (:id, :user, 'interviewing', true)
            """),
            {"id": session_id, "user": USER},
        )
        await connection.execute(
            text("""
                INSERT INTO app.turns (session_id, turn_no, stage_index, question)
                VALUES (:id, 1, 0, '未结束的私人问题？')
            """),
            {"id": session_id},
        )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            denied_list = await client.get("/v1/admin/curation-items", headers=USER_HEADERS)
            assert denied_list.status_code == 403
            queue = await client.get("/v1/admin/curation-items", headers=ADMIN_HEADERS)
            assert session_id not in {UUID(row["session_id"]) for row in queue.json()["sources"]}
            selected = await client.post(
                "/v1/admin/curation-items",
                headers=ADMIN_HEADERS,
                json={"source_session_id": str(session_id), "source_turn_no": 1},
            )
            assert selected.status_code == 404
    finally:
        await cleanup_session(session_id)


@pytest.mark.asyncio
async def test_local_release_failure_does_not_block_deleted_session(monkeypatch):
    session_id = uuid4()
    await fixture_session(session_id)
    async with engine.begin() as connection:
        await connection.execute(
            text("UPDATE app.interview_sessions SET source_handle = :handle WHERE id = :id"),
            {"id": session_id, "handle": uuid4().hex + uuid4().hex[:11]},
        )
    original_settings = prepare_service.get_settings
    monkeypatch.setattr(
        prepare_service,
        "get_settings",
        lambda: SimpleNamespace(
            local_runtime_url="http://127.0.0.1:1",
            desktop_instance_token=original_settings().desktop_instance_token,
        ),
    )
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.delete(f"/v1/interviews/{session_id}", headers=USER_HEADERS)
            assert response.status_code == 204, response.text
            assert (
                await client.get(f"/v1/interviews/{session_id}", headers=USER_HEADERS)
            ).status_code == 404
    finally:
        await cleanup_session(session_id)


@pytest.mark.asyncio
async def test_trace_retention_purges_only_rows_older_than_thirty_days():
    session_id = uuid4()
    old_trace = uuid4()
    recent_trace = uuid4()
    await fixture_session(session_id)
    try:
        async with engine.begin() as connection:
            for trace_id, age in ((old_trace, 31), (recent_trace, 29)):
                await connection.execute(
                    text("""
                        INSERT INTO telemetry.model_calls
                            (trace_id, session_id, operation_name, provider, model, status,
                             attempt_no, started_at, finished_at, latency_ms)
                        VALUES (:trace, :id, 'retention_test', 'test', 'test', 'succeeded',
                                1, now() - make_interval(days => :age),
                                now() - make_interval(days => :age), 0)
                    """),
                    {"trace": trace_id, "id": session_id, "age": age},
                )
        await purge_expired_traces()
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("SELECT trace_id FROM telemetry.model_calls WHERE session_id = :id"),
                {"id": session_id},
            )
            assert {row[0] for row in rows} == {recent_trace}
    finally:
        await cleanup_session(session_id)
