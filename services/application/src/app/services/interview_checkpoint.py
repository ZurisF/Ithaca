"""LangGraph Redis persistence, interview execution lock and disposable events."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from uuid import UUID, uuid4

from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from redis.asyncio import Redis

from app.services.errors import AppError
from app.settings import get_settings

INTERVIEW_NAMESPACE = "interview"
FINALIZATION_NAMESPACE = "finalization"


def graph_config(session_id: UUID, namespace: str) -> dict[str, dict[str, str]]:
    return {
        "configurable": {
            "thread_id": f"{session_id}:{namespace}",
        }
    }


@asynccontextmanager
async def checkpoint_saver() -> AsyncIterator[AsyncRedisSaver]:
    """Open the production LangGraph saver with the active-checkpoint retention window."""
    async with AsyncRedisSaver.from_conn_string(
        get_settings().redis_url,
        ttl={"default_ttl": 60 * 24 * 30, "refresh_on_read": True},
    ) as saver:
        yield saver


async def read_checkpoint(session_id: UUID, namespace: str = INTERVIEW_NAMESPACE) -> dict | None:
    """Read the latest LangGraph channel values for public projection and recovery."""
    async with checkpoint_saver() as saver:
        checkpoint = await saver.aget(graph_config(session_id, namespace))
    if checkpoint is None:
        return None
    values = checkpoint.get("channel_values")
    return dict(values) if isinstance(values, dict) else None


async def delete_checkpoint(session_id: UUID) -> None:
    """Delete every graph namespace for one session after terminal publication."""
    async with checkpoint_saver() as saver:
        await saver.adelete_thread(f"{session_id}:{INTERVIEW_NAMESPACE}")
        await saver.adelete_thread(f"{session_id}:{FINALIZATION_NAMESPACE}")


async def notify_current_changed(session_id: UUID, event: str) -> None:
    redis = Redis.from_url(get_settings().redis_url)
    try:
        await redis.publish(f"interview:{session_id}:events", event)
    finally:
        await redis.aclose()


@asynccontextmanager
async def execution_lock(session_id: UUID) -> AsyncIterator[None]:
    redis = Redis.from_url(get_settings().redis_url)
    key = f"interview:{session_id}:execution"
    token = str(uuid4())
    try:
        acquired = await redis.set(key, token, nx=True, ex=60)
    except Exception as exc:
        await redis.aclose()
        raise AppError(503, "dependency_unavailable", "面试执行锁暂时不可用。", True) from exc
    if not acquired:
        await redis.aclose()
        raise AppError(409, "operation_in_progress", "当前面试操作仍在进行。", True)

    async def renew() -> None:
        while True:
            await asyncio.sleep(20)
            await redis.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] "
                "then return redis.call('expire', KEYS[1], 60) else return 0 end",
                1,
                key,
                token,
            )

    renewal = asyncio.create_task(renew())
    try:
        yield
    finally:
        renewal.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await renewal
        with suppress(Exception):
            await redis.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] "
                "then return redis.call('del', KEYS[1]) else return 0 end",
                1,
                key,
                token,
            )
        await redis.aclose()
