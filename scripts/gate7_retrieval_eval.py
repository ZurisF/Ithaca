"""Offline fixed-query retrieval and RAGAS evaluation; never used by the API."""

import argparse
import asyncio
import hashlib
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from openai import AsyncOpenAI
from ragas.llms.base import llm_factory
from ragas.metrics.collections import ContextRecall, ContextRelevance
from sqlalchemy import text

from app.bank.retrieval import LocalBGEModels, QuestionRetriever
from app.bank.seed import load_seed_batch
from app.db import engine
from app.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests/fixtures/gate7/retrieval_queries.json"


def _score(candidates: list[str], gold: list[str]) -> dict:
    positions = [index for index, question in enumerate(candidates) if question in gold]
    ideal = sum(1 / math.log2(index + 2) for index in range(min(len(gold), 3)))
    found = sum(question in candidates for question in gold)
    return {
        "recall_at_3": found / len(gold),
        "ndcg_at_3": (sum(1 / math.log2(index + 2) for index in positions) / ideal)
        if ideal
        else None,
        "exact_duplicate_count": len(candidates) - len(set(candidates)),
        "human_adaptation": None,
        "semantic_duplicate_count": None,
    }


async def _ragas(metric, **kwargs) -> dict:
    try:
        result = await asyncio.wait_for(metric.ascore(**kwargs), timeout=120)
        value = float(result.value)
        if not math.isfinite(value):
            return {"value": None, "error": "non_finite_score"}
        return {"value": value, "error": None}
    except Exception as exc:  # noqa: BLE001 - preserve a failed judge as missing
        return {"value": None, "error": type(exc).__name__}


async def main(output: Path) -> None:
    settings = get_settings()
    if not settings.model_api_key or not settings.model_name:
        raise RuntimeError("RAGAS judge model is not configured")
    raw = CASES.read_bytes()
    cases = json.loads(raw)
    seed_questions = {item.question for item in load_seed_batch().questions}
    assert all(set(case["gold_questions"]) <= seed_questions for case in cases)
    async with engine.connect() as connection:
        bank_count = await connection.scalar(text("SELECT count(*) FROM bank.questions"))
    if bank_count < 537:
        raise RuntimeError("reviewed question bank is not fully imported")

    models = LocalBGEModels(settings.embedding_model_path, settings.reranker_model_path)
    retriever = QuestionRetriever(
        models,
        min_score=settings.retrieval_min_score,
        deadline_seconds=settings.retrieval_timeout_seconds,
        attempts=settings.retrieval_max_attempts,
    )
    async with AsyncOpenAI(
        api_key=settings.model_api_key,
        base_url=settings.model_base_url,
        timeout=90,
        max_retries=0,
    ) as judge_client:
        judge = llm_factory(settings.model_name, client=judge_client)
        relevance = ContextRelevance(llm=judge, max_retries=1)
        recall = ContextRecall(llm=judge)
        results = []
        for case in cases:
            session_id = uuid4()
            async with engine.begin() as connection:
                await connection.execute(
                    text("INSERT INTO app.interview_sessions (id, user_id) VALUES (:id, :user)"),
                    {
                        "id": session_id,
                        "user": "00000000-0000-4000-8000-000000000001",
                    },
                )
            try:
                started = time.monotonic()
                candidates = await retriever.retrieve_for_turn(
                    session_id, case["query"], case["topic"], limit=3
                )
                elapsed_ms = round((time.monotonic() - started) * 1000)
            finally:
                async with engine.begin() as connection:
                    await connection.execute(
                        text("DELETE FROM app.interview_sessions WHERE id = :id"),
                        {"id": session_id},
                    )
            contexts = [item.question for item in candidates]
            scores = _score(contexts, case["gold_questions"])
            scores["ragas_context_relevance"] = (
                await _ragas(relevance, user_input=case["query"], retrieved_contexts=contexts)
                if contexts
                else {"value": None, "error": "no_contexts"}
            )
            scores["ragas_context_recall"] = (
                await _ragas(
                    recall,
                    user_input=case["query"],
                    retrieved_contexts=contexts,
                    reference=case["reference"],
                )
                if contexts
                else {"value": None, "error": "no_contexts"}
            )
            results.append(
                {
                    "id": case["id"],
                    "topic": case["topic"],
                    "query": case["query"],
                    "reference": case["reference"],
                    "gold_questions": case["gold_questions"],
                    "candidates": contexts,
                    "retrieval_latency_ms": elapsed_ms,
                    **scores,
                }
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "evaluated_at": datetime.now(UTC).isoformat(),
                "case_sha256": hashlib.sha256(raw).hexdigest(),
                "bank_count": bank_count,
                "retrieval_k": 3,
                "ragas_version": "0.4.3",
                "judge_model": settings.model_name,
                "cases": results,
            },
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.output))
