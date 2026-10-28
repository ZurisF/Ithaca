"""Reviewed seed source and exact-question idempotent database import."""

from uuid import uuid4

import pytest
from sqlalchemy import text

from app.bank.seed import SeedBatch, SeedQuestion, import_seed_batch, load_seed_batch
from app.db import engine


class ControlledEmbedder:
    def __init__(self) -> None:
        self.calls = 0

    def encode_corpus(self, questions: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[0.001] * 1024 for _ in questions]


def test_reviewed_source_excludes_archive_and_nested_translation_items() -> None:
    batch = load_seed_batch()
    assert batch.source_total == 573
    assert batch.source_duplicates == 36
    assert len(batch.questions) == 537
    assert all(
        not item.question.startswith("What does your day-to-day") for item in batch.questions
    )


@pytest.mark.asyncio
async def test_seed_import_replay_preserves_existing_question_rows() -> None:
    suffix = uuid4().hex
    first = f"Gate 3 synthetic retrieval question A {suffix}?"
    second = f"Gate 3 synthetic retrieval question B {suffix}?"
    batch = SeedBatch(
        (
            SeedQuestion(first, "agent"),
            SeedQuestion(second, "rag"),
        ),
        source_total=2,
        source_duplicates=0,
    )
    embedder = ControlledEmbedder()
    try:
        first_run = await import_seed_batch(batch, embedder)
        assert first_run.inserted == 2
        assert first_run.existing == 0
        assert first_run.verified_indexed == 2
        assert embedder.calls == 1
        async with engine.begin() as connection:
            row = await connection.execute(
                text("""
                    SELECT topic_path, embedding IS NOT NULL, lexical_document IS NOT NULL
                    FROM bank.questions WHERE question = :question
                """),
                {"question": first},
            )
            assert row.one() == ("agent", True, True)
            await connection.execute(
                text(
                    "UPDATE bank.questions SET topic_path = 'security' WHERE question = :question"
                ),
                {"question": first},
            )
        replay = await import_seed_batch(batch, embedder)
        assert replay.inserted == 0
        assert replay.existing == 2
        assert replay.verified_indexed == 2
        assert embedder.calls == 1
        async with engine.connect() as connection:
            topic = await connection.scalar(
                text("SELECT topic_path FROM bank.questions WHERE question = :question"),
                {"question": first},
            )
            assert topic == "security"
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM bank.questions WHERE question = ANY(CAST(:items AS text[]))"),
                {"items": [first, second]},
            )
