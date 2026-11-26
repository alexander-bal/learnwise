"""The startup and periodic sweep (Processing FR-5) beyond its happy path."""

import asyncio
import logging

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.db.engine import create_db_engine, create_sessionmaker
from app.db.migrate import migrate
from app.services.maintenance import run_sweeper, sweep_once
from tests.integration.reviews_helpers import execute, rows, scalar, start, wait_until

OLD = "2000-01-01T00:00:00.000Z"


async def test_the_sweep_leaves_a_reviews_calls_to_the_worker(
    client: httpx.AsyncClient, migrated: Settings, sessionmaker: async_sessionmaker
) -> None:
    review_id = await start(client)
    await execute(
        sessionmaker,
        "INSERT INTO llm_calls (id, request_id, operation, provider, model, status, review_id, "
        "created_at) VALUES ('review-call', 'r', 'judge', 'simulator', 'fake-judge', 'running', "
        ":review, :old), ('process-call', 'r', 'process', 'simulator', 'fake', 'running', NULL, "
        ":old)",
        review=review_id,
        old=OLD,
    )

    write = create_db_engine(migrated.database_url, immediate=True)
    try:
        await sweep_once(migrated, create_sessionmaker(write))
    finally:
        await write.dispose()

    statuses = {
        r.id: (r.status, r.error_code)
        for r in await rows(sessionmaker, "SELECT id, status, error_code FROM llm_calls")
    }
    # An old call of a review is not the API's to close: its worker recovers the review.
    assert statuses == {"review-call": ("running", None), "process-call": ("error", "interrupted")}


async def test_the_sweeper_outlives_a_failing_sweep_and_sweeps_again(
    settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    # A database with no schema yet: the first sweeps fail for real ("no such table").
    write = create_db_engine(settings.database_url, immediate=True)
    sessionmaker = create_sessionmaker(write)
    fast = settings.model_copy(update={"sweep_interval_seconds": 0.05})
    sweeper = asyncio.create_task(run_sweeper(fast, sessionmaker))
    try:

        async def warned_twice() -> bool:
            return sum(r.getMessage() == "sweep failed" for r in caplog.records) >= 2

        with caplog.at_level(logging.WARNING):
            await wait_until(warned_twice, what="two failed sweeps")
        assert not sweeper.done()

        migrate(settings.sync_database_url, settings.database_path)
        await execute(
            sessionmaker,
            "INSERT INTO idempotency_requests (endpoint, key, request_hash, status, created_at) "
            "VALUES ('/process', 'stale', 'h', 'completed', :old)",
            old=OLD,
        )

        async def swept() -> bool:
            count = await scalar(sessionmaker, "SELECT count(*) FROM idempotency_requests")
            return count == 0

        await wait_until(swept, what="the stale key to be swept")
        assert not sweeper.done()
    finally:
        sweeper.cancel()
        await asyncio.gather(sweeper, return_exceptions=True)
        await write.dispose()
