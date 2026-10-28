"""Local model spans cross runtimes as metadata only and are idempotent."""

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import text

from app.db import engine
from app.main import app
from app.settings import get_settings


@pytest.mark.asyncio
async def test_internal_trace_rejects_content_and_replay_is_idempotent() -> None:
    trace_id = uuid4()
    now = datetime.now(UTC).isoformat()
    payload = {
        "trace_id": str(trace_id),
        "session_id": None,
        "operation_name": "observer_step",
        "provider": "controlled",
        "model": "test-model",
        "prompt_version": "observer-v1",
        "status": "succeeded",
        "attempt_no": 1,
        "started_at": now,
        "finished_at": now,
        "latency_ms": 10,
        "input_tokens": 20,
        "output_tokens": 5,
        "error_code": None,
    }
    url = "/internal/v1/model-traces"
    token = get_settings().desktop_instance_token
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.post(url, json=payload)).status_code == 401
        headers = {"Authorization": f"Bearer {token}"}
        assert (
            await client.post(url, headers=headers, json={**payload, "prompt": "PRIVATE"})
        ).status_code == 400
        try:
            first = await client.post(url, headers=headers, json=payload)
            second = await client.post(url, headers=headers, json=payload)
            assert first.status_code == second.status_code == 202
            async with engine.connect() as connection:
                count = await connection.scalar(
                    text("SELECT count(*) FROM telemetry.model_calls WHERE trace_id = :id"),
                    {"id": trace_id},
                )
            assert count == 1
        finally:
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM telemetry.model_calls WHERE trace_id = :id"),
                    {"id": trace_id},
                )
