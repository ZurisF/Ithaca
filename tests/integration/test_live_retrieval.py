"""Opt-in fixed seed replay with real local BGE-M3 and BGE reranker."""

import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.bank.retrieval import LocalBGEModels, QuestionRetriever
from app.bank.seed import load_seed_batch
from app.db import engine
from app.settings import get_settings

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_RETRIEVAL") != "1", reason="opt-in local model replay"
)


@pytest.mark.asyncio
async def test_exact_seed_query_survives_real_hybrid_retrieval() -> None:
    sample = load_seed_batch().questions[0]
    session_id = uuid4()
    settings = get_settings()
    async with engine.begin() as connection:
        count = await connection.scalar(text("SELECT count(*) FROM bank.questions"))
        assert count >= 537, "import the reviewed seed bank before live retrieval replay"
        await connection.execute(
            text("""
            INSERT INTO app.interview_sessions (id, user_id)
            VALUES (:id, :user_id)
        """),
            {"id": session_id, "user_id": UUID("00000000-0000-4000-8000-000000000001")},
        )
    try:
        retriever = QuestionRetriever(
            LocalBGEModels(settings.embedding_model_path, settings.reranker_model_path),
            deadline_seconds=90,
        )
        result = await retriever.retrieve_for_turn(
            session_id, sample.question, sample.topic_path, limit=3
        )
        assert result
        assert any(candidate.question == sample.question for candidate in result)
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM app.interview_sessions WHERE id = :id"), {"id": session_id}
            )
