"""Recover incomplete interview decisions from PostgreSQL after process interruption."""

import asyncio
import logging
from contextlib import suppress

from app.api.model_dependency import get_model_adapter
from app.bank.retrieval import get_retriever
from app.db import session_factory
from app.domain.access import Identity
from app.repositories.interview import recoverable_sessions
from app.services.errors import AppError
from app.services.interview import _active_interrupt, _load_context, _run_decisions
from app.services.interview_checkpoint import execution_lock, read_checkpoint
from app.settings import get_settings

logger = logging.getLogger(__name__)


async def recover_once() -> int:
    settings = get_settings()
    if not settings.model_api_key or not settings.model_name:
        return 0
    async with session_factory() as db, db.begin():
        candidates = await recoverable_sessions(db)
    recovered = 0
    for item in candidates:
        session_id = item["id"]
        try:
            # Scan locks end before processing; the execution lock and PG publish checks guard effects.
            async with execution_lock(session_id):
                checkpoint = await read_checkpoint(session_id)
                # Reuse the owner's command path for recovery, with the stored owner ID.
                identity = Identity(id=item["user_id"], role="user", display_name=None)
                async with session_factory() as db:
                    *_, trigger = await _load_context(db, identity, session_id)
                    if _active_interrupt(checkpoint, trigger):
                        continue
                    await _run_decisions(
                        db, identity, session_id, get_model_adapter(), get_retriever()
                    )
                recovered += 1
        except AppError as exc:
            if exc.code != "operation_in_progress":
                logger.warning("interview_recovery_failed code=%s", exc.code)
        except Exception:  # noqa: BLE001 - isolate each recovery candidate
            logger.warning("interview_recovery_failed")
    return recovered


async def run_worker() -> None:
    while True:
        try:
            await recover_once()
        except Exception:  # noqa: BLE001 - retry dependency outage on next scan
            logger.warning("interview_recovery_scan_failed")
        await asyncio.sleep(5)


async def stop_worker(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
