"""Prompt Improvement failure paths (FR-2, FR-3, NFR-1) beyond the acceptance criteria."""

import logging
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.db.engine import create_db_engine, create_sessionmaker
from app.services import reviews
from tests.integration.conftest import Sim
from tests.integration.db_lock import write_lock
from tests.integration.reviews_helpers import (
    REVIEW_ENV,
    TRAFFIC_A,
    Worker,
    calls,
    execute,
    judged,
    process_all,
    rows,
    scalar,
    start,
    wait_final,
    wait_until,
)


@pytest.fixture(autouse=True)
def review_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name, value in REVIEW_ENV.items():
        monkeypatch.setenv(name, value)
    yield


@pytest.fixture
async def write(migrated: Settings) -> AsyncIterator[async_sessionmaker]:
    engine = create_db_engine(migrated.database_url, immediate=True)
    yield create_sessionmaker(engine)
    await engine.dispose()


async def review_row(sessionmaker: async_sessionmaker, review_id: str):  # noqa: ANN201
    return (await rows(sessionmaker, "SELECT * FROM reviews WHERE id = :id", id=review_id))[0]


async def wait_status(sessionmaker: async_sessionmaker, review_id: str, status: str) -> None:
    async def reached() -> bool:
        current = await scalar(
            sessionmaker, "SELECT status FROM reviews WHERE id = :id", id=review_id
        )
        return current == status

    await wait_until(reached, what=f"review {review_id} to be {status}")


async def wait_for_log(
    caplog: pytest.LogCaptureFixture, message: str, within: float = 15.0
) -> None:
    async def logged() -> bool:
        return any(r.getMessage() == message for r in caplog.records)

    await wait_until(logged, within=within, what=f"the log line {message!r}")


async def a_review_whose_profile_was_removed(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker
) -> str:
    """A review frozen on a provider profile the running code no longer has, as after a
    deploy that renamed or removed it."""
    await process_all(client, TRAFFIC_A[:2])
    review_id = await start(client)
    await execute(
        sessionmaker, "UPDATE reviews SET provider = 'retired' WHERE id = :id", id=review_id
    )
    return review_id


# ---------------------------------------------------------------- FR-3: ending an attempt


async def test_an_attempt_that_cannot_set_up_crashes_and_leaves_the_review_running(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker,
    migrated: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Pins today's behavior that the xfail below reports as a bug."""
    review_id = await a_review_whose_profile_was_removed(client, sessionmaker)
    worker = Worker(migrated.model_copy(update={"review_lease_seconds": 60})).start()
    try:
        with caplog.at_level(logging.ERROR, logger="app.worker"):
            await wait_for_log(caplog, "review attempt crashed")
        review = await review_row(sessionmaker, review_id)
        assert (review.status, review.error_code, review.attempts) == ("running", None, 1)
        assert worker.running
    finally:
        await worker.close()


@pytest.mark.xfail(
    strict=True,
    reason="BUG: ReviewRunner is built outside run_attempt's try (services/reviews.py:835), "
    "so a setup error records nothing and the review stays running until its lease expires",
)
async def test_an_attempt_that_cannot_set_up_ends_with_internal_error(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker,
    migrated: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    review_id = await a_review_whose_profile_was_removed(client, sessionmaker)
    # A lease far longer than the test, so its expiry cannot end the attempt instead.
    worker = Worker(migrated.model_copy(update={"review_lease_seconds": 60})).start()
    try:
        with caplog.at_level(logging.ERROR, logger="app.worker"):
            await wait_for_log(caplog, "review attempt crashed")
        review = await review_row(sessionmaker, review_id)
        # FR-3: an attempt that ends early, for any reason, records its error and goes back
        # to pending; an error with no code of its own is `internal_error`.
        assert (review.status, review.error_code, review.attempts) == (
            "pending",
            "internal_error",
            1,
        )
        assert review.next_attempt_at is not None
    finally:
        await worker.close()


async def test_a_lease_that_expires_mid_call_is_an_interrupted_attempt(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, migrated: Settings
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("delay", seconds=5)
    first = Worker(migrated).start()
    review_id = await start(client)

    async def in_flight() -> bool:
        return await calls(sessionmaker, review_id, "judge", "running") == 1

    await wait_until(in_flight, what="a judge call in flight")
    await first.kill()

    second = Worker(migrated).start()
    try:
        await wait_status(sessionmaker, review_id, "pending")
        review = await review_row(sessionmaker, review_id)
        assert (review.error_code, review.attempts) == ("interrupted", 1)
        assert review.owner_token is None and review.next_attempt_at is not None
        assert await calls(sessionmaker, review_id, "judge", "running") == 0
        [call] = await rows(
            sessionmaker,
            "SELECT status, error_code FROM llm_calls WHERE review_id = :id",
            id=review_id,
        )
        assert (call.status, call.error_code) == ("error", "interrupted")

        sim.clear()
        done = await wait_final(sessionmaker, review_id)
        assert (done.outcome, done.attempts) == ("promoted", 2)
    finally:
        await second.close()


async def test_a_worker_without_the_lease_cannot_end_or_fail_the_attempt(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker,
    write: async_sessionmaker,
    migrated: Settings,
) -> None:
    review_id = await start(client)
    review = await reviews.claim(write, migrated, "mine")
    assert review is not None and review.id == review_id
    await execute(
        sessionmaker, "UPDATE reviews SET owner_token = 'other' WHERE id = :id", id=review_id
    )

    ended = await reviews.end_attempt(write, review, "mine", migrated, "internal_error", "x")
    failed = await reviews.fail(write, review, "mine", "provider_misconfigured", "x")

    assert (ended, failed) == (False, False)
    after = await review_row(sessionmaker, review_id)
    assert (after.status, after.owner_token, after.error_code) == ("running", "other", None)


# ------------------------------------------------------- FR-3: expiry, before and during


async def test_a_waiting_review_past_its_time_limit_fails_without_another_attempt(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker, worker_settings: Settings
) -> None:
    await process_all(client, TRAFFIC_A[:2])
    review_id = await start(client)
    await execute(
        sessionmaker,
        "UPDATE reviews SET expires_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = :id",
        id=review_id,
    )
    worker = Worker(worker_settings).start()
    try:
        review = await wait_final(sessionmaker, review_id)
    finally:
        await worker.close()

    assert (review.status, review.error_code, review.attempts) == ("failed", "review_expired", 0)
    assert (
        await scalar(
            sessionmaker, "SELECT count(*) FROM llm_calls WHERE review_id = :id", id=review_id
        )
        == 0
    )
    assert (await client.post("/reviews")).status_code == 202


async def test_a_review_that_expires_during_its_attempt_fails_and_closes_its_calls(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker_settings: Settings
) -> None:
    await process_all(client, TRAFFIC_A)
    review_id = await start(client)
    # Claimed with a time limit it will outlast: 30 calls of 50 ms take far longer.
    await execute(
        sessionmaker,
        "UPDATE reviews SET expires_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '+0.4 seconds') "
        "WHERE id = :id",
        id=review_id,
    )
    sim.fault("delay", seconds=0.05)
    worker = Worker(worker_settings).start()
    try:
        review = await wait_final(sessionmaker, review_id)
    finally:
        await worker.close()

    assert (review.status, review.error_code, review.attempts) == ("failed", "review_expired", 1)
    assert 0 < await judged(sessionmaker, review_id) < 20
    assert review.candidate_prompt_id is None
    assert await calls(sessionmaker, review_id, "judge", "running") == 0
    assert (await client.post("/reviews")).status_code == 202


# ------------------------------------------- FR-3 / NFR-1: a model server that is down


@pytest.fixture
def worker_settings(migrated: Settings) -> Settings:
    return migrated


async def run_until_pending(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker, settings: Settings
) -> str:
    worker = Worker(settings).start()
    try:
        review_id = await start(client)
        await wait_until(lambda: _attempt_ended(sessionmaker, review_id), what="the attempt to end")
    finally:
        await worker.close()
    return review_id


async def _attempt_ended(sessionmaker: async_sessionmaker, review_id: str) -> bool:
    review = await review_row(sessionmaker, review_id)
    return review.status == "pending" and review.attempts == 1


async def test_a_judge_that_keeps_failing_trips_the_breaker_and_ends_the_attempt(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, migrated: Settings
) -> None:
    await process_all(client, TRAFFIC_A[:2])
    sim.fault("5xx", model="fake-judge")
    # 5 failures in a row open the breaker before the 6th of the call's attempts.
    settings = migrated.model_copy(update={"breaker_threshold": 5, "review_max_attempts": 6})

    review_id = await run_until_pending(client, sessionmaker, settings)

    review = await review_row(sessionmaker, review_id)
    assert review.error_code == "circuit_open"
    assert review.next_attempt_at is not None
    assert await calls(sessionmaker, review_id, "judge", "error") == 5
    assert await calls(sessionmaker, review_id, "judge", "running") == 0


async def test_a_judge_that_keeps_failing_below_the_breaker_is_provider_unavailable(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, migrated: Settings
) -> None:
    await process_all(client, TRAFFIC_A[:2])
    sim.fault("5xx", model="fake-judge")
    settings = migrated.model_copy(update={"breaker_threshold": 10, "review_max_attempts": 6})

    review_id = await run_until_pending(client, sessionmaker, settings)

    review = await review_row(sessionmaker, review_id)
    assert review.error_code == "provider_unavailable"
    assert await calls(sessionmaker, review_id, "judge", "error") == 6


async def test_a_judge_that_never_answers_times_out_each_attempt(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, migrated: Settings
) -> None:
    await process_all(client, TRAFFIC_A[:2])
    sim.fault("never_answer", model="fake-judge")
    settings = migrated.model_copy(
        update={
            "breaker_threshold": 10,
            "review_max_attempts": 3,
            "review_attempt_timeout_seconds": 0.2,
        }
    )

    review_id = await run_until_pending(client, sessionmaker, settings)

    review = await review_row(sessionmaker, review_id)
    assert review.error_code == "provider_unavailable"
    assert await calls(sessionmaker, review_id, "judge", "timeout") == 3
    assert await calls(sessionmaker, review_id, "judge") == 3


# ---------------------------------------------- FR-2: a model server that refuses a call


async def test_a_judge_that_refuses_marks_outputs_unjudgeable_without_retrying(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker_settings: Settings
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("reject", model="fake-judge")
    worker = Worker(worker_settings).start()
    try:
        review_id = await start(client)
        review = await wait_final(sessionmaker, review_id)
    finally:
        await worker.close()

    assert (review.status, review.outcome) == ("completed", "no_changes")
    # ProviderRejected is final: one attempt per output, not six.
    assert await calls(sessionmaker, review_id, "judge") == 10
    assert await calls(sessionmaker, review_id, "judge", "success") == 0
    assert (
        await scalar(
            sessionmaker,
            "SELECT count(*) FROM review_judgments WHERE review_id = :id "
            "AND json_type(expected_output) = 'null'",
            id=review_id,
        )
        == 10
    )
    assert await calls(sessionmaker, review_id, "improve_prompt") == 0


async def test_a_refused_proposal_completes_as_no_proposal_after_one_attempt(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker_settings: Settings
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("delay", seconds=0.02)
    worker = Worker(worker_settings).start()
    try:
        review_id = await start(client)

        async def base_judged() -> bool:
            return await judged(sessionmaker, review_id) == 10

        await wait_until(base_judged, what="the base judgments")
        sim.fault("reject", model="fake-judge")
        review = await wait_final(sessionmaker, review_id)
    finally:
        await worker.close()

    assert (review.status, review.outcome) == ("completed", "no_proposal")
    assert await calls(sessionmaker, review_id, "improve_prompt") == 1
    assert await scalar(sessionmaker, "SELECT count(*) FROM prompt_versions") == 1
    assert await scalar(sessionmaker, "SELECT active_version_id FROM prompt_state") == 1


async def test_refused_candidate_outputs_score_zero_and_reject_the_candidate(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker_settings: Settings
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("delay", seconds=0.02)
    worker = Worker(worker_settings).start()
    try:
        review_id = await start(client)

        async def candidate_stored() -> bool:
            return bool(
                await scalar(
                    sessionmaker,
                    "SELECT candidate_prompt_id FROM reviews WHERE id = :id",
                    id=review_id,
                )
            )

        await wait_until(candidate_stored, what="the candidate")
        sim.fault("reject", model="fake")
        review = await wait_final(sessionmaker, review_id)
    finally:
        await worker.close()

    assert (review.status, review.outcome) == ("completed", "rejected")
    detail = (await client.get(f"/reviews/{review_id}")).json()
    assert (detail["base_score"], detail["candidate_score"]) == (18, 0)
    assert await calls(sessionmaker, review_id, "evaluate_candidate") == 10
    versions = (await client.get("/prompts")).json()
    assert [(v["id"], v["status"]) for v in versions] == [(2, "rejected"), (1, "active")]


# ------------------------------------------------------------ FR-3: a locked database


async def test_a_worker_keeps_polling_while_the_database_cannot_be_written(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker,
    migrated: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await process_all(client, TRAFFIC_A)
    worker = Worker(migrated).start()
    try:
        # Claiming needs the write lock: it waits busy_timeout (5 s), fails, and the worker
        # logs it and polls again instead of dying.
        with write_lock(migrated.database_path), caplog.at_level(logging.WARNING):
            await wait_for_log(caplog, "worker could not claim a review", within=15)
            assert worker.running
        assert worker.running

        review_id = await start(client)
        review = await wait_final(sessionmaker, review_id)
    finally:
        await worker.close()

    assert (review.status, review.outcome) == ("completed", "promoted")
