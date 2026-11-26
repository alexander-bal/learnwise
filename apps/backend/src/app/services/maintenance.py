"""Housekeeping the API runs at startup and every minute (Processing FR-3, FR-5)."""

import asyncio
import logging

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.db.time import now_iso
from app.models import IdempotencyRequest, LlmCall

log = logging.getLogger(__name__)


async def close_interrupted_calls(
    sessionmaker: async_sessionmaker, older_than_seconds: float
) -> int:
    """Close calls left `running` by a dead process, outside any review.

    Only calls older than the request deadline, so no call still in flight is closed.
    """
    now = now_iso()
    async with sessionmaker() as session, session.begin():
        result = await session.execute(
            update(LlmCall)
            .where(
                LlmCall.status == "running",
                LlmCall.review_id.is_(None),
                LlmCall.created_at < now_iso(-older_than_seconds),
            )
            .values(
                status="error",
                error_code="interrupted",
                error_message="the process died during the call",
                completed_at=now,
            )
            .execution_options(synchronize_session=False)
        )
    return result.rowcount


async def remove_expired_idempotency_records(
    sessionmaker: async_sessionmaker, ttl_hours: float
) -> int:
    async with sessionmaker() as session, session.begin():
        result = await session.execute(
            delete(IdempotencyRequest)
            .where(IdempotencyRequest.created_at < now_iso(-ttl_hours * 3600))
            .execution_options(synchronize_session=False)
        )
    return result.rowcount


async def sweep_once(settings: Settings, sessionmaker: async_sessionmaker) -> None:
    closed = await close_interrupted_calls(sessionmaker, settings.request_deadline_seconds)
    removed = await remove_expired_idempotency_records(sessionmaker, settings.idempotency_ttl_hours)
    if closed or removed:
        log.info("swept", extra={"interrupted_calls": closed, "expired_keys": removed})


async def run_sweeper(settings: Settings, sessionmaker: async_sessionmaker) -> None:
    """Sweep now and then every interval, in the background so /process is never delayed."""
    while True:
        try:
            await sweep_once(settings, sessionmaker)
        except Exception:
            # The next sweep tries again; the loop must outlive any one failure.
            log.warning("sweep failed", exc_info=True)
        await asyncio.sleep(settings.sweep_interval_seconds)
