import asyncio
import contextlib
import logging
import signal
import time
import uuid

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.db.engine import create_db_engine, create_sessionmaker
from app.db.migrate import SchemaStatus, classify, script_directory
from app.llm.gateway import LlmGateway
from app.llm.provider import Providers
from app.models import Review
from app.services import reviews
from app.services.health import schema_revision

log = logging.getLogger(__name__)

EXIT_SCHEMA_NEWER = 3


class ReviewWorker:
    """Runs the open review in attempts (Prompt Improvement FR-3).

    It polls for a due review, holds its lease while an attempt runs, and stops after the
    call in flight on a termination signal or once the schema is newer than its code.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        read: async_sessionmaker,
        write: async_sessionmaker,
        gateway: LlmGateway,
        stop: asyncio.Event,
    ) -> None:
        self._settings = settings
        self._read = read
        self._write = write
        self._gateway = gateway
        self._stop = stop
        self._script = script_directory()
        self._token = uuid.uuid4().hex
        self.exit_code = 0

    async def run(self) -> int:
        log.info("worker started")
        while not self._stop.is_set():
            if await self._schema_newer():
                return self.exit_code
            review = await self._next_review()
            if review is not None:
                await self._run_attempt(review)
                continue
            poll = self._settings.worker_poll_seconds
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=poll)
        if self.exit_code:
            log.error("worker stopped: the schema is newer than its code")
        else:
            log.info("worker stopped on signal")
        return self.exit_code

    async def _schema_newer(self) -> bool:
        try:
            async with self._read() as session:
                revision = await schema_revision(session)
        except SQLAlchemyError:
            log.warning("worker could not read the schema version", exc_info=True)
            return False
        if classify(revision, self._script) is not SchemaStatus.NEWER:
            return False
        log.error("schema is newer than this code", extra={"revision": revision})
        # Stop as on a termination signal; the supervisor starts the new code.
        self.exit_code = EXIT_SCHEMA_NEWER
        self._stop.set()
        return True

    async def _next_review(self) -> Review | None:
        try:
            await reviews.recover_expired_leases(self._write, self._settings)
            await reviews.expire_pending(self._write)
            return await reviews.claim(self._write, self._settings, self._token)
        except SQLAlchemyError:
            log.warning("worker could not claim a review", exc_info=True)
            return None

    async def _run_attempt(self, review: Review) -> None:
        settings = self._settings
        attempt = asyncio.create_task(
            reviews.run_attempt(
                settings, self._gateway, self._read, self._write, review, self._token, self._stop
            )
        )
        tick = min(settings.worker_poll_seconds, settings.review_lease_renew_seconds)
        next_renewal = time.monotonic() + settings.review_lease_renew_seconds
        stopped_at: float | None = None
        try:
            while not attempt.done():
                await asyncio.wait({attempt}, timeout=tick)
                if attempt.done():
                    break
                if stopped_at is None:
                    await self._schema_newer()
                    if self._stop.is_set():
                        stopped_at = time.monotonic()
                elif time.monotonic() - stopped_at >= settings.shutdown_grace_seconds:
                    # The call in flight did not finish within the grace period.
                    await _cancel(attempt)
                    await reviews.end_attempt(
                        self._write,
                        review,
                        self._token,
                        settings,
                        "terminated",
                        "the worker was stopped during a call",
                    )
                    return
                if time.monotonic() >= next_renewal:
                    next_renewal = time.monotonic() + settings.review_lease_renew_seconds
                    if not await self._renew(review):
                        log.warning("review lease lost", extra={"review_id": review.id})
                        await _cancel(attempt)
                        return
        except asyncio.CancelledError:
            # The worker itself is going away: its attempt goes with it and writes nothing.
            await _cancel(attempt)
            raise
        if not attempt.cancelled() and (exc := attempt.exception()) is not None:
            log.error("review attempt crashed", exc_info=exc, extra={"review_id": review.id})

    async def _renew(self, review: Review) -> bool:
        try:
            return await reviews.renew_lease(self._write, review.id, self._token, self._settings)
        except SQLAlchemyError:
            log.warning("could not renew the review lease", exc_info=True)
            return True  # try again on the next tick; the lease outlives a few misses


async def _cancel(task: asyncio.Task[None]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


async def run_worker(settings: Settings, stop: asyncio.Event | None = None) -> int:
    """The review worker. Returns the process exit code: non-zero when the schema moved
    past this code, so the supervisor starts it again on the new code (FR-3).

    `stop` stands in for a termination signal; without one, SIGTERM and SIGINT set it.
    """
    if stop is None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

    engine = create_db_engine(settings.database_url)
    write_engine = create_db_engine(settings.database_url, immediate=True)
    read = create_sessionmaker(engine)
    write = create_sessionmaker(write_engine)
    providers = Providers(settings)
    gateway = LlmGateway(settings, write, providers.adapter_for)
    worker = ReviewWorker(settings, read=read, write=write, gateway=gateway, stop=stop)
    try:
        return await worker.run()
    finally:
        await providers.aclose()
        await write_engine.dispose()
        await engine.dispose()
