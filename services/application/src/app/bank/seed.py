"""Import only the reviewed topic files into the single PostgreSQL question bank."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.bank.vectors import checked_vector
from app.db import engine

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "agent-interview/按考点"
TOPIC_CONFIG = ROOT / "packages/planning_assets/question_bank_seed.json"
TOPICS = ROOT / "packages/planning_assets/topics.yaml"
FILE_LINK = re.compile(r"^- \[[^]]+\]\(([^/)]+\.md)\) — (\d+) 题$")
TOTAL = re.compile(r"当前共 (\d+) 道题")


@dataclass(frozen=True)
class SeedQuestion:
    question: str
    topic_path: str


@dataclass(frozen=True)
class SeedBatch:
    questions: tuple[SeedQuestion, ...]
    source_total: int
    source_duplicates: int


@dataclass(frozen=True)
class ImportStats:
    source_total: int
    source_duplicates: int
    source_unique: int
    existing: int
    inserted: int
    concurrent_conflicts: int
    verified_indexed: int


class DenseEmbedder(Protocol):
    def encode_corpus(self, questions: list[str]) -> list[list[float]]: ...


def load_seed_batch(source: Path = SOURCE) -> SeedBatch:
    """Parse README's direct 11-file allowlist and only top-level questions."""
    source = source.resolve(strict=True)
    readme = (source / "README.md").read_text(encoding="utf-8")
    config = json.loads(TOPIC_CONFIG.read_text(encoding="utf-8"))
    topic_paths = {
        item["path"] for item in json.loads(TOPICS.read_text(encoding="utf-8"))["topics"]
    }
    file_topics = config["file_topics"]
    if len(file_topics) != 11 or not set(file_topics.values()) <= topic_paths:
        raise ValueError("seed topic config is not the reviewed 11-file mapping")
    entries = [
        (match.group(1), int(match.group(2)))
        for line in readme.splitlines()
        if (match := FILE_LINK.fullmatch(line))
    ]
    names = [name for name, _ in entries]
    if len(entries) != 11 or len(names) != len(set(names)) or set(names) != set(file_topics):
        raise ValueError("README topic allowlist and reviewed topic mapping differ")
    expected_total_match = TOTAL.search(readme)
    if expected_total_match is None:
        raise ValueError("README has no reviewed question count")
    expected_total = int(expected_total_match.group(1))
    if sum(count for _, count in entries) != expected_total:
        raise ValueError("README file counts do not match its total")

    seen: set[str] = set()
    questions: list[SeedQuestion] = []
    source_total = 0
    for name, expected_count in entries:
        path = source / name
        if path.is_symlink() or path.resolve(strict=True).parent != source:
            raise ValueError("seed file must be a regular file inside the allowlisted directory")
        candidates = [
            line[2:].strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.startswith("- ")
        ]
        if len(candidates) != expected_count or any(not question for question in candidates):
            raise ValueError(f"reviewed count differs for {name}")
        source_total += len(candidates)
        for question in candidates:
            if question not in seen:
                seen.add(question)
                questions.append(SeedQuestion(question, file_topics[name]))
    return SeedBatch(tuple(questions), source_total, source_total - len(questions))


def lexical_terms(question: str) -> str:
    """Use the same Chinese and technical-word segmentation for index and query."""
    import jieba

    words = [
        term.casefold()
        for chunk in jieba.cut_for_search(question)
        for term in re.findall(r"[A-Za-z][A-Za-z0-9_+#.\-]*|\d+|[\u4e00-\u9fff]+", chunk)
    ]
    return " ".join(words)


async def import_seed_batch(
    batch: SeedBatch, embedder: DenseEmbedder, *, db_engine: AsyncEngine = engine
) -> ImportStats:
    """Encode outside transactions; use exact-question conflicts to preserve edited rows."""
    values = [item.question for item in batch.questions]
    async with db_engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT question FROM bank.questions WHERE question = ANY(CAST(:items AS text[]))"
            ),
            {"items": values},
        )
        existing = {row[0] for row in rows}
    missing = [item for item in batch.questions if item.question not in existing]
    if missing:
        encoded = embedder.encode_corpus([item.question for item in missing])
        if len(encoded) != len(missing):
            raise ValueError("BGE-M3 returned a different number of vectors")
        vectors = [checked_vector(vector) for vector in encoded]
    else:
        vectors = []

    inserted = 0
    async with db_engine.begin() as connection:
        for item, vector in zip(missing, vectors, strict=True):
            result = await connection.execute(
                text("""
                    INSERT INTO bank.questions
                        (id, question, topic_path, embedding, lexical_document)
                    VALUES
                        (:id, :question, :topic, CAST(:embedding AS vector),
                         to_tsvector('simple', :lexical))
                    ON CONFLICT (question) DO NOTHING
                    RETURNING id
                """),
                {
                    "id": uuid4(),
                    "question": item.question,
                    "topic": item.topic_path,
                    "embedding": vector,
                    "lexical": lexical_terms(item.question),
                },
            )
            inserted += int(result.scalar_one_or_none() is not None)
    async with db_engine.connect() as connection:
        verified = await connection.execute(
            text("""
                SELECT count(*), count(*) FILTER (
                    WHERE embedding IS NOT NULL AND lexical_document IS NOT NULL
                )
                FROM bank.questions WHERE question = ANY(CAST(:items AS text[]))
            """),
            {"items": values},
        )
        present, indexed = verified.one()
    if present != len(batch.questions) or indexed != present:
        raise ValueError("seed import is incomplete or an existing row lacks a retrieval index")
    return ImportStats(
        source_total=batch.source_total,
        source_duplicates=batch.source_duplicates,
        source_unique=len(batch.questions),
        existing=len(existing),
        inserted=inserted,
        concurrent_conflicts=len(missing) - inserted,
        verified_indexed=indexed,
    )
