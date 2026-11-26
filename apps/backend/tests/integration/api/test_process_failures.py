"""/process when the database fails under it (Processing FR-1: no detail leaks, no stuck state)."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.main import create_app
from tests.integration.api.test_process import BILLING, post, rows
from tests.integration.conftest import Sim
from tests.integration.db_lock import write_lock


async def test_a_database_that_cannot_be_written_is_a_500_and_the_service_recovers(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker,
    migrated: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # No idempotency key, so the first write is the call row; it waits 5 s, then fails.
    with write_lock(migrated.database_path), caplog.at_level(logging.ERROR):
        response = await post(client, BILLING, rid="locked-1")

    assert response.status_code == 500
    assert response.json() == {
        "code": "internal_error",
        "message": "Internal error",
        "retryable": True,
    }
    assert response.headers["X-Request-ID"] == "locked-1"
    assert "locked" not in response.text
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == [
        "unhandled error"
    ]
    assert await rows(sessionmaker, "SELECT id FROM llm_calls") == []
    assert await rows(sessionmaker, "SELECT id FROM samples") == []

    # Nothing is left stuck: the breaker did not count it, and the next request succeeds.
    assert (await post(client, BILLING)).status_code == 200
    [sample] = await rows(sessionmaker, "SELECT input FROM samples")
    assert sample["input"] == BILLING


@pytest.fixture
async def app_client(migrated: Settings) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    app = create_app()
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield app, client


async def test_a_request_that_gets_no_slot_before_its_deadline_is_a_504_without_a_call(
    app_client: tuple[FastAPI, httpx.AsyncClient],
    sessionmaker: async_sessionmaker,
    migrated: Settings,
) -> None:
    app, client = app_client
    # Every slot of the pool taken, as under overload, for longer than the whole deadline.
    # (Held directly: real calls free their slot on every attempt timeout, so timing alone
    # could not keep the pool full for the deadline.)
    pool = app.state.gateway._pools["process"]
    for _ in range(migrated.process_concurrency):
        await pool.acquire()
    try:
        started = time.monotonic()
        response = await post(client, BILLING, rid="no-slot")
        elapsed = time.monotonic() - started
    finally:
        for _ in range(migrated.process_concurrency):
            pool.release()

    assert response.status_code == 504
    assert response.json()["code"] == "deadline_exceeded"
    assert response.json()["retryable"] is True
    assert migrated.request_deadline_seconds <= elapsed < migrated.request_deadline_seconds + 0.5
    # It never reached the model server: no call row, no sample, and the breaker not counted.
    assert await rows(sessionmaker, "SELECT id FROM llm_calls") == []
    assert await rows(sessionmaker, "SELECT id FROM samples") == []
    assert app.state.gateway.breaker_states() == {"simulator/fake": "closed"}

    # The slots are free again: the next request goes through.
    assert (await post(client, BILLING)).status_code == 200


@pytest.fixture
def long_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    # Longer than the whole request deadline (1.5 s), even with the backoff's jitter.
    monkeypatch.setenv("BACKOFF_BASE_SECONDS", "10")


async def test_a_backoff_longer_than_the_time_left_ends_the_request_at_once(
    long_backoff: None, client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker
) -> None:
    sim.fault("5xx")

    started = time.monotonic()
    response = await post(client, BILLING)
    elapsed = time.monotonic() - started

    assert response.status_code == 504
    assert response.json()["code"] == "deadline_exceeded"
    # It does not sleep through a wait it cannot finish, and does not try a second time.
    assert elapsed < 1.0
    [call] = await rows(sessionmaker, "SELECT attempt, status, error_code FROM llm_calls")
    assert (call["attempt"], call["status"], call["error_code"]) == (
        1,
        "error",
        "provider_unavailable",
    )


async def test_a_failed_trial_reopens_the_breaker_for_another_interval(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, migrated: Settings
) -> None:
    sim.fault("5xx")
    while len(await rows(sessionmaker, "SELECT id FROM llm_calls")) < 5:
        assert (await post(client, BILLING)).status_code == 503
    assert (await post(client, BILLING)).json()["code"] == "circuit_open"

    # The interval passes with the model still down: one trial goes through and fails.
    await asyncio.sleep(migrated.breaker_open_seconds + 0.05)
    trial = await post(client, BILLING)
    # The failed trial reopened the breaker, so the request's own retry is refused.
    assert trial.status_code == 503
    assert trial.json()["code"] == "circuit_open"
    assert "Retry-After" in trial.headers
    trial_calls = await rows(sessionmaker, "SELECT status FROM llm_calls ORDER BY created_at")
    assert len(trial_calls) == 6 and trial_calls[-1]["status"] == "error"

    # It is open again: calls fail fast without reaching the model, until the next interval.
    again = await post(client, BILLING)
    assert again.json()["code"] == "circuit_open"
    assert len(await rows(sessionmaker, "SELECT id FROM llm_calls")) == 6

    sim.clear()
    await asyncio.sleep(migrated.breaker_open_seconds + 0.05)
    assert (await post(client, BILLING)).status_code == 200
