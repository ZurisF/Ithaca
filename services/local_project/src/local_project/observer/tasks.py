"""Short-lived, process-local coalescing of Observer work by operation ID."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from local_project.errors import LocalError

TTL_SECONDS = 300
MAX_OPERATIONS = 128


@dataclass
class _Operation:
    session_id: UUID
    source_handle: str
    task: asyncio.Task[str]
    expires_at: float


class ObserverTasks:
    def __init__(self) -> None:
        self._operations: dict[UUID, _Operation] = {}
        self._lock = asyncio.Lock()

    async def run(
        self,
        operation_id: UUID,
        session_id: UUID,
        source_handle: str,
        work: Callable[[], Awaitable[str]],
    ) -> str:
        async with self._lock:
            now = time.monotonic()
            for key, entry in list(self._operations.items()):
                if entry.task.done() and entry.expires_at <= now:
                    self._operations.pop(key)
            entry = self._operations.get(operation_id)
            if entry is not None:
                if entry.session_id != session_id or entry.source_handle != source_handle:
                    raise LocalError(409, "operation_conflict", "操作标识已用于其他目录观察。")
            else:
                if len(self._operations) >= MAX_OPERATIONS:
                    for key, old in list(self._operations.items()):
                        if old.task.done():
                            self._operations.pop(key)
                            break
                if len(self._operations) >= MAX_OPERATIONS:
                    raise LocalError(503, "observer_busy", "本地观察任务繁忙，请稍后重试。")
                entry = _Operation(
                    session_id,
                    source_handle,
                    asyncio.create_task(work()),
                    now + TTL_SECONDS,
                )
                self._operations[operation_id] = entry
        try:
            return await asyncio.shield(entry.task)
        except Exception:
            async with self._lock:
                if self._operations.get(operation_id) is entry and entry.task.done():
                    self._operations.pop(operation_id)
            raise


observer_tasks = ObserverTasks()
