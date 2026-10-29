"""Redis execution lock and disposable interview interrupt projection."""

import asyncio
import json
from contextlib import asynccontextmanager, suppress
from uuid import UUID, uuid4

from redis.asyncio import Redis

from app.services.errors import AppError
from app.settings import get_settings


def checkpoint_key(session_id: UUID) -> str:
    return f"interview:{session_id}:checkpoint"


def finalization_checkpoint_key(session_id: UUID) -> str:
    return f"interview:{session_id}:finalization"


async def delete_checkpoint(session_id: UUID) -> None:
    redis = Redis.from_url(get_settings().redis_url)
    try:
        await redis.delete(checkpoint_key(session_id), finalization_checkpoint_key(session_id))
    finally:
        await redis.aclose()


async def read_finalization_checkpoint(session_id: UUID) -> str | None:
    redis = Redis.from_url(get_settings().redis_url)
    try:
        raw = await redis.get(finalization_checkpoint_key(session_id))
        return raw.decode() if raw else None
    finally:
        await redis.aclose()


async def write_finalization_checkpoint(session_id: UUID, phase: str) -> None:
    redis = Redis.from_url(get_settings().redis_url)
    try:
        await redis.set(finalization_checkpoint_key(session_id), phase, ex=60 * 60 * 24 * 30)
    finally:
        await redis.aclose()


async def read_checkpoint(session_id: UUID) -> dict | None:
    redis = Redis.from_url(get_settings().redis_url)
    try:
        raw = await redis.get(checkpoint_key(session_id))
        return json.loads(raw) if raw else None
    finally:
        await redis.aclose()


async def write_checkpoint(
    session_id: UUID,
    *,
    awaiting: str,
    error: str | None = None,
    pending: dict | None = None,
) -> None:
    redis = Redis.from_url(get_settings().redis_url)
    try:
        raw = await redis.get(checkpoint_key(session_id))
        old = json.loads(raw) if raw else {}
        state = {
            "awaiting": awaiting,
            "last_error_code": error,
            "compact": old.get("compact"),
            "compacted_through_turn_no": old.get("compacted_through_turn_no", 0),
        }
        if pending is not None:
            state["pending"] = pending
        await redis.set(
            checkpoint_key(session_id),
            json.dumps(state, ensure_ascii=False),
            ex=60 * 60 * 24 * 30,
        )
    finally:
        await redis.aclose()


async def write_compact(session_id: UUID, *, compact: str, through_turn_no: int) -> None:
    redis = Redis.from_url(get_settings().redis_url)
    try:
        raw = await redis.get(checkpoint_key(session_id))
        state = json.loads(raw) if raw else {}
        if through_turn_no <= state.get("compacted_through_turn_no", 0):
            return
        state["compact"] = compact
        state["compacted_through_turn_no"] = through_turn_no
        await redis.set(
            checkpoint_key(session_id), json.dumps(state, ensure_ascii=False), ex=60 * 60 * 24 * 30
        )
    finally:
        await redis.aclose()


async def notify_current_changed(session_id: UUID) -> None:
    redis = Redis.from_url(get_settings().redis_url)
    try:
        await redis.publish(f"interview:{session_id}:events", "current_changed")
    finally:
        await redis.aclose()


@asynccontextmanager
async def execution_lock(session_id: UUID):
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
