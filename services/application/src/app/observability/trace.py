"""Persist only the approved model-call metadata fields."""

from sqlalchemy import text

from app.db import session_factory
from model_adapter import TraceSpan


class PostgresTraceSink:
    async def write(self, span: TraceSpan) -> None:
        async with session_factory() as db, db.begin():
            await db.execute(
                text("""
                    INSERT INTO telemetry.model_calls (
                        trace_id, session_id, operation_name, provider, model,
                        prompt_version, status, attempt_no, started_at, finished_at,
                        latency_ms, input_tokens, output_tokens, error_code
                    ) VALUES (
                        :trace_id, :session_id, :operation_name, :provider, :model,
                        :prompt_version, :status, :attempt_no, :started_at, :finished_at,
                        :latency_ms, :input_tokens, :output_tokens, :error_code
                    )
                    ON CONFLICT (trace_id) DO NOTHING
                """),
                span.__dict__,
            )
