"""Forward content-free model spans; buffer briefly if Application is unavailable."""

import asyncio
import logging
from collections import deque
from dataclasses import asdict

import httpx

from local_project.settings import get_settings
from model_adapter import TraceSpan


class BufferedTraceSink:
    def __init__(self) -> None:
        self.pending: deque[dict] = deque(maxlen=100)
        self.lock = asyncio.Lock()

    async def write(self, span: TraceSpan) -> None:
        payload = asdict(span)
        payload["trace_id"] = str(span.trace_id)
        payload["session_id"] = str(span.session_id) if span.session_id else None
        payload["started_at"] = span.started_at.isoformat()
        payload["finished_at"] = span.finished_at.isoformat()
        async with self.lock:
            settings = get_settings()
            queued = [*self.pending, payload]
            self.pending.clear()
            for index, item in enumerate(queued):
                try:
                    async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                        response = await client.post(
                            f"{settings.app_runtime_url}/internal/v1/model-traces",
                            headers={"Authorization": f"Bearer {settings.desktop_instance_token}"},
                            json=item,
                        )
                    if response.status_code != 202:
                        raise ValueError("trace endpoint rejected metadata")
                except (httpx.RequestError, ValueError):
                    self.pending.extend(queued[index:])
                    logging.getLogger(__name__).warning("trace_buffered")
                    return


trace_sink = BufferedTraceSink()
