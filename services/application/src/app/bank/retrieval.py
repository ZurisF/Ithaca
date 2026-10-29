"""One online retrieval boundary: dense + FTS + RRF + topic prior + reranker."""

import asyncio
import logging
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from threading import Lock
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.bank.seed import lexical_terms
from app.bank.vectors import checked_vector
from app.db import engine
from app.observability.trace import PostgresTraceSink
from app.settings import get_settings
from model_adapter import TraceSpan

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuestionCandidate:
    question_id: UUID
    question: str


class RetrievalModels(Protocol):
    async def embed_query(self, query: str) -> list[float]: ...

    async def embed_document(self, question: str) -> list[float]: ...

    async def rerank(self, query: str, questions: list[str]) -> list[float]: ...


class LocalBGEModels:
    """Load the reviewed local models once; blocking inference runs off the event loop."""

    def __init__(self, embedding_path: str, reranker_path: str) -> None:
        self.embedding_path = embedding_path
        self.reranker_path = reranker_path
        self._embedding = None
        self._reranker = None
        self._load_lock = Lock()

    def _embed(self, query: str) -> list[float]:
        with self._load_lock:
            if self._embedding is None:
                from FlagEmbedding import BGEM3FlagModel

                self._embedding = BGEM3FlagModel(self.embedding_path, use_fp16=False)
        result = self._embedding.encode_queries(
            [query],
            batch_size=1,
            max_length=512,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        return result["dense_vecs"][0].tolist()

    def _embed_document(self, question: str) -> list[float]:
        with self._load_lock:
            if self._embedding is None:
                from FlagEmbedding import BGEM3FlagModel

                self._embedding = BGEM3FlagModel(self.embedding_path, use_fp16=False)
        result = self._embedding.encode_corpus(
            [question],
            batch_size=1,
            max_length=512,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        return result["dense_vecs"][0].tolist()

    def _rerank(self, query: str, questions: list[str]) -> list[float]:
        with self._load_lock:
            if self._reranker is None:
                from FlagEmbedding import FlagReranker

                self._reranker = FlagReranker(self.reranker_path, use_fp16=False, normalize=True)
        result = self._reranker.compute_score([(query, question) for question in questions])
        try:
            iter(result)
        except TypeError:
            return [float(result)]
        return [float(score) for score in result]

    async def embed_query(self, query: str) -> list[float]:
        return await asyncio.to_thread(self._embed, query)

    async def embed_document(self, question: str) -> list[float]:
        return await asyncio.to_thread(self._embed_document, question)

    async def rerank(self, query: str, questions: list[str]) -> list[float]:
        return await asyncio.to_thread(self._rerank, query, questions)


def _topic_weight(candidate: str, selected: str) -> float:
    if candidate == selected:
        return 1.2
    if candidate.startswith(f"{selected}.") or selected.startswith(f"{candidate}."):
        return 1.1
    if candidate.split(".", 1)[0] == selected.split(".", 1)[0]:
        return 1.05
    return 1.0


class QuestionRetriever:
    def __init__(
        self,
        models: RetrievalModels,
        *,
        db_engine: AsyncEngine = engine,
        min_score: float = 0.1,
        deadline_seconds: float = 30,
        attempts: int = 2,
    ) -> None:
        self.models = models
        self.db_engine = db_engine
        self.min_score = min_score
        self.deadline_seconds = deadline_seconds
        self.attempts = attempts
        self.trace_sink = PostgresTraceSink()

    async def _trace(
        self,
        session_id: UUID,
        operation: str,
        started_at: datetime,
        tick: float,
        status: str,
        attempt: int,
    ) -> None:
        settings = get_settings()
        try:
            await self.trace_sink.write(
                TraceSpan(
                    trace_id=uuid4(),
                    session_id=session_id,
                    operation_name=operation,
                    provider="local_bge",
                    model=(
                        settings.embedding_model_path
                        if operation == "retrieval_embedding"
                        else settings.reranker_model_path
                    ),
                    prompt_version=None,
                    status=status,
                    attempt_no=attempt,
                    started_at=started_at,
                    finished_at=datetime.now(UTC),
                    latency_ms=max(0, round((time.monotonic() - tick) * 1000)),
                    input_tokens=None,
                    output_tokens=None,
                    error_code=None if status == "succeeded" else "retrieval_dependency_failed",
                )
            )
        except Exception:  # noqa: BLE001 - telemetry cannot change retrieval outcome
            logger.warning("retrieval_trace_write_failed")

    async def _model_call(self, session_id: UUID, operation: str, attempt: int, call):
        started_at = datetime.now(UTC)
        tick = time.monotonic()
        status = "failed"
        try:
            result = await call
            status = "succeeded"
            return result
        finally:
            await self._trace(session_id, operation, started_at, tick, status, attempt)

    async def _once(
        self,
        session_id: UUID,
        query_text: str,
        topic_path: str,
        limit: int,
        attempt: int,
    ) -> list[QuestionCandidate]:
        embedding = checked_vector(
            await self._model_call(
                session_id, "retrieval_embedding", attempt, self.models.embed_query(query_text)
            )
        )
        terms = sorted(set(lexical_terms(query_text).split()))
        lexical_query = " | ".join(term for term in terms[:48] if term.replace("_", "").isalnum())
        async with self.db_engine.connect() as connection:
            recent = await connection.execute(
                text("""
                SELECT question FROM app.turns WHERE session_id = :session_id
                ORDER BY turn_no DESC LIMIT 3
            """),
                {"session_id": session_id},
            )
            cooldown = {row[0] for row in recent}
            dense = await connection.execute(
                text("""
                SELECT id, question, topic_path FROM bank.questions
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:embedding AS vector), id
                LIMIT 30
            """),
                {"embedding": embedding},
            )
            dense_rows = dense.mappings().all()
            if lexical_query:
                lexical = await connection.execute(
                    text("""
                    SELECT id, question, topic_path FROM bank.questions
                    WHERE lexical_document @@ to_tsquery('simple', :query)
                    ORDER BY ts_rank_cd(lexical_document, to_tsquery('simple', :query)) DESC, id
                    LIMIT 30
                """),
                    {"query": lexical_query},
                )
                lexical_rows = lexical.mappings().all()
            else:
                lexical_rows = []
        merged: dict[UUID, tuple[str, str, float]] = {}
        for rows in (dense_rows, lexical_rows):
            for rank, row in enumerate(rows, 1):
                prior = merged.get(row["id"])
                score = (prior[2] if prior else 0.0) + 1.0 / (60 + rank)
                merged[row["id"]] = (row["question"], row["topic_path"], score)
        shortlist = sorted(
            (
                (id, question, score * _topic_weight(topic, topic_path))
                for id, (question, topic, score) in merged.items()
                if question not in cooldown
            ),
            key=lambda row: (-row[2], str(row[0])),
        )[:12]
        if not shortlist:
            return []
        scores = await self._model_call(
            session_id,
            "retrieval_reranker",
            attempt,
            self.models.rerank(query_text, [item[1] for item in shortlist]),
        )
        if len(scores) != len(shortlist) or any(not math.isfinite(score) for score in scores):
            raise ValueError("invalid reranker scores")
        ranked = sorted(
            (
                (item[0], item[1], float(score), item[2])
                for item, score in zip(shortlist, scores, strict=True)
                if score >= self.min_score
            ),
            key=lambda row: (-row[2], -row[3], str(row[0])),
        )
        return [QuestionCandidate(id, question) for id, question, _, _ in ranked[:limit]]

    async def retrieve_for_turn(
        self, session_id: UUID, query_text: str, topic_path: str, limit: int = 3
    ) -> list[QuestionCandidate]:
        if limit < 0 or limit > 3:
            raise ValueError("retrieval limit must be between 0 and 3")
        if limit == 0 or not query_text.strip():
            return []
        started = time.monotonic()
        for attempt in range(1, self.attempts + 1):
            remaining = self.deadline_seconds - (time.monotonic() - started)
            if remaining <= 0:
                break
            try:
                return await asyncio.wait_for(
                    self._once(session_id, query_text, topic_path, limit, attempt),
                    timeout=remaining,
                )
            except Exception:  # noqa: BLE001 - RAG failure must degrade to zero candidates
                logger.warning("retrieval_attempt_failed", extra={"attempt": attempt})
        return []


@lru_cache(maxsize=1)
def get_retriever() -> QuestionRetriever:
    settings = get_settings()
    return QuestionRetriever(
        LocalBGEModels(settings.embedding_model_path, settings.reranker_model_path),
        min_score=settings.retrieval_min_score,
        deadline_seconds=settings.retrieval_timeout_seconds,
        attempts=settings.retrieval_max_attempts,
    )
