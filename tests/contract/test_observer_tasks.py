"""Local operation IDs merge concurrent work and reject mismatched reuse."""

import asyncio
from uuid import uuid4

import pytest

from local_project.errors import LocalError
from local_project.observer.tasks import ObserverTasks


@pytest.mark.asyncio
async def test_observer_operation_coalesces_concurrent_and_replayed_calls() -> None:
    tasks = ObserverTasks()
    operation_id = uuid4()
    session_id = uuid4()
    started = asyncio.Event()
    finish = asyncio.Event()
    calls = 0

    async def work() -> str:
        nonlocal calls
        calls += 1
        started.set()
        await finish.wait()
        return "snapshot"

    first = asyncio.create_task(tasks.run(operation_id, session_id, "handle-a", work))
    await started.wait()
    second = asyncio.create_task(tasks.run(operation_id, session_id, "handle-a", work))
    await asyncio.sleep(0)
    finish.set()
    assert await asyncio.gather(first, second) == ["snapshot", "snapshot"]
    assert await tasks.run(operation_id, session_id, "handle-a", work) == "snapshot"
    assert calls == 1

    with pytest.raises(LocalError) as conflict:
        await tasks.run(operation_id, session_id, "handle-b", work)
    assert conflict.value.code == "operation_conflict"


@pytest.mark.asyncio
async def test_failed_observer_operation_can_retry() -> None:
    tasks = ObserverTasks()
    operation_id = uuid4()
    session_id = uuid4()
    calls = 0

    async def work() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise LocalError(503, "observer_failed", "try again")
        return "snapshot"

    with pytest.raises(LocalError):
        await tasks.run(operation_id, session_id, "handle-a", work)
    assert await tasks.run(operation_id, session_id, "handle-a", work) == "snapshot"
    assert calls == 2
