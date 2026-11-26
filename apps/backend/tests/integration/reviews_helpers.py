"""Shared harness for the review tests (Prompt Improvement Acceptance Criteria)."""

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.worker import run_worker

# Shortened in proportion, so their order is kept: a lease outlives a few renewals, a
# call's retries end well within an attempt, and the first wait between attempts (1 minute)
# outlasts the breaker's open interval (15 s, shortened to 0.4 s in FAST_ENV).
REVIEW_ENV = {
    "WORKER_POLL_SECONDS": "0.02",
    "REVIEW_ATTEMPT_TIMEOUT_SECONDS": "1",
    "REVIEW_BACKOFF_BASE_SECONDS": "0.005",
    "REVIEW_BACKOFF_MAX_SECONDS": "0.02",
    "REVIEW_RETRY_BASE_SECONDS": "0.5",
    "REVIEW_RETRY_MAX_SECONDS": "2",
    "REVIEW_LEASE_SECONDS": "0.5",
    "REVIEW_LEASE_RENEW_SECONDS": "0.1",
    "SHUTDOWN_GRACE_SECONDS": "2",
}

TRAFFIC_A = [
    "I have a question about billing",
    "billing charged me twice",
    "my shipping is late",
    "where is my shipping",
    "a technical issue at login",
    "technical issue with the app",
    "please process my cancellation",
    "cancellation of my plan",
    "hello there",
    "thanks for your help",
]


async def process_all(client: httpx.AsyncClient, messages: list[str]) -> None:
    for message in messages:
        response = await client.post("/process", json={"message": message})
        assert response.status_code == 200, response.text
        # Distinct created_at, so "most recent" is well defined.
        await asyncio.sleep(0.003)


async def classify(client: httpx.AsyncClient, message: str) -> str:
    response = await client.post("/process", json={"message": message})
    assert response.status_code == 200, response.text
    return response.json()["record"]["intent"]


async def start(client: httpx.AsyncClient) -> str:
    response = await client.post("/reviews")
    assert response.status_code == 202, response.text
    return response.json()["review_id"]


async def scalar(sessionmaker: async_sessionmaker, sql: str, **params: Any) -> Any:
    async with sessionmaker() as session:
        return await session.scalar(text(sql), params)


async def rows(sessionmaker: async_sessionmaker, sql: str, **params: Any) -> list[Any]:
    async with sessionmaker() as session:
        return list((await session.execute(text(sql), params)).all())


async def execute(sessionmaker: async_sessionmaker, sql: str, **params: Any) -> None:
    async with sessionmaker() as session, session.begin():
        await session.execute(text(sql), params)


async def wait_until(
    check: Callable[[], Awaitable[bool]], *, within: float = 15.0, what: str = "condition"
) -> None:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        if await check():
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"timed out waiting for {what}")


async def wait_final(sessionmaker: async_sessionmaker, review_id: str, within: float = 30.0) -> Any:
    async def done() -> bool:
        status = await scalar(
            sessionmaker, "SELECT status FROM reviews WHERE id = :id", id=review_id
        )
        return status in ("completed", "failed")

    await wait_until(done, within=within, what=f"review {review_id} to end")
    return (await rows(sessionmaker, "SELECT * FROM reviews WHERE id = :id", id=review_id))[0]


async def judged(sessionmaker: async_sessionmaker, review_id: str) -> int:
    return await scalar(
        sessionmaker,
        "SELECT count(*) FROM review_judgments WHERE review_id = :id "
        "AND expected_output IS NOT NULL",
        id=review_id,
    )


async def calls(
    sessionmaker: async_sessionmaker, review_id: str, operation: str, status: str | None = None
) -> int:
    sql = "SELECT count(*) FROM llm_calls WHERE review_id = :id AND operation = :op"
    if status is not None:
        sql += " AND status = :status"
    return await scalar(sessionmaker, sql, id=review_id, op=operation, status=status)


class Worker:
    """The worker process, as a task: killed by cancelling it, stopped by its stop event."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stop = asyncio.Event()
        self.task: asyncio.Task[int] | None = None

    def start(self) -> Worker:
        self.stop = asyncio.Event()
        self.task = asyncio.create_task(run_worker(self.settings, self.stop))
        return self

    @property
    def running(self) -> bool:
        return self.task is not None and not self.task.done()

    async def kill(self) -> None:
        assert self.task is not None
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.task

    async def terminate(self) -> int:
        assert self.task is not None
        self.stop.set()
        return await asyncio.wait_for(self.task, timeout=10)

    async def wait_exit(self) -> int:
        assert self.task is not None
        return await asyncio.wait_for(self.task, timeout=10)

    async def close(self) -> None:
        if self.task is not None and not self.task.done():
            await self.kill()


async def one_success_per_result(sessionmaker: async_sessionmaker, review_id: str) -> None:
    """Every stored result has exactly one successful call."""
    duplicates = await rows(
        sessionmaker,
        "SELECT operation, sample_id, prompt_version_id, count(*) FROM llm_calls "
        "WHERE review_id = :id AND status = 'success' "
        "GROUP BY operation, sample_id, prompt_version_id HAVING count(*) > 1",
        id=review_id,
    )
    assert duplicates == []
