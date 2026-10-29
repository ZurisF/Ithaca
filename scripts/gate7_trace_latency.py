"""Report content-free model and retrieval latency from persisted trace metadata."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.db import engine


async def main() -> None:
    since = datetime.now(UTC) - timedelta(days=7)
    async with engine.connect() as connection:
        rows = await connection.execute(
            text("""
                SELECT operation_name, provider, status, count(*) AS samples,
                       min(started_at) AS first_started_at,
                       max(finished_at) AS last_finished_at,
                       min(latency_ms) AS min_ms,
                       max(latency_ms) AS max_ms,
                       percentile_cont(ARRAY[0.5, 0.95, 0.99])
                           WITHIN GROUP (ORDER BY latency_ms) AS percentiles_ms
                FROM telemetry.model_calls
                WHERE started_at >= :since
                GROUP BY operation_name, provider, status
                ORDER BY operation_name, provider, status
            """),
            {"since": since},
        )
        report = [
            {
                "operation": row.operation_name,
                "provider": row.provider,
                "status": row.status,
                "samples": row.samples,
                "first_started_at": row.first_started_at.isoformat(),
                "last_finished_at": row.last_finished_at.isoformat(),
                "min_ms": row.min_ms,
                "p50_ms": round(row.percentiles_ms[0], 1),
                "p95_ms": round(row.percentiles_ms[1], 1),
                "p99_ms": round(row.percentiles_ms[2], 1),
                "max_ms": row.max_ms,
            }
            for row in rows
        ]
    print(json.dumps({"since": since.isoformat(), "groups": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
