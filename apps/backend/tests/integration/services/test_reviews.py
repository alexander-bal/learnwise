"""Prompt Improvement Acceptance Criteria AC-1 to AC-5, with the worker as a task."""

import asyncio
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.db.migrate import head_revision
from app.worker import EXIT_SCHEMA_NEWER
from tests.integration.conftest import Sim
from tests.integration.reviews_helpers import (
    REVIEW_ENV,
    TRAFFIC_A,
    Worker,
    calls,
    classify,
    execute,
    judged,
    one_success_per_result,
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
async def worker(migrated: Settings) -> AsyncIterator[Worker]:
    w = Worker(migrated)
    yield w
    await w.close()


async def scores(client: httpx.AsyncClient, review_id: str) -> tuple[int | None, int | None]:
    detail = (await client.get(f"/reviews/{review_id}")).json()
    return detail["base_score"], detail["candidate_score"]


async def assert_ac1_result(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker, review_id: str
) -> None:
    review = await wait_final(sessionmaker, review_id)
    assert (review.status, review.outcome) == ("completed", "promoted")
    assert await scores(client, review_id) == (18, 20)
    assert await calls(sessionmaker, review_id, "judge", "success") == 20
    assert await calls(sessionmaker, review_id, "improve_prompt", "success") == 1
    assert await calls(sessionmaker, review_id, "evaluate_candidate", "success") == 10
    await one_success_per_result(sessionmaker, review_id)


# ------------------------------------------------------------------------------ AC-1


async def test_ac1_a_review_runs_in_the_background_and_promotes_a_better_prompt(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("delay", seconds=0.02)
    worker.start()

    first = await client.post("/reviews")
    assert first.status_code == 202
    review_id = first.json()["review_id"]
    assert (
        await scalar(
            sessionmaker,
            "SELECT count(*) FROM llm_calls WHERE review_id = :id AND status = 'success'",
            id=review_id,
        )
        == 0
    )

    second = await client.post("/reviews")
    assert second.status_code == 409
    assert second.json()["code"] == "review_in_progress"
    assert second.json()["retryable"] is True
    assert second.json()["review_id"] == review_id
    assert await scalar(sessionmaker, "SELECT count(*) FROM reviews") == 1

    review = await wait_final(sessionmaker, review_id)
    assert review.outcome == "promoted"
    detail = (await client.get(f"/reviews/{review_id}")).json()
    assert detail["samples"] == 10
    assert (
        await scalar(
            sessionmaker,
            "SELECT count(*) FROM review_judgments WHERE review_id = :id",
            id=review_id,
        )
        == 20
    )
    in_error = [p for p in detail["judgments"] if p["base"]["in_error"]]
    assert sorted(p["base"]["expected"]["intent"] for p in in_error) == ["cancellation"] * 2
    assert not any(p["candidate"]["in_error"] for p in detail["judgments"])
    assert (detail["base_score"], detail["candidate_score"]) == (18, 20)

    version = (await client.get("/prompts")).json()[0]
    assert (version["id"], version["parent_id"], version["status"]) == (2, 1, "active")
    assert version["change_reason"]

    assert await calls(sessionmaker, review_id, "judge", "success") == 20
    assert await calls(sessionmaker, review_id, "improve_prompt", "success") == 1
    assert await calls(sessionmaker, review_id, "evaluate_candidate", "success") == 10
    assert (
        await scalar(
            sessionmaker,
            "SELECT count(*) FROM llm_calls WHERE review_id = :id AND operation = "
            "'evaluate_candidate' AND model != 'fake'",
            id=review_id,
        )
        == 0
    )
    assert (
        await scalar(
            sessionmaker,
            "SELECT count(*) FROM llm_calls WHERE review_id = :id AND status != 'success'",
            id=review_id,
        )
        == 0
    )
    assert await scalar(sessionmaker, "SELECT count(*) FROM samples") == 10

    # AC-3: right after the promotion, version 2 has produced no samples.
    again = await wait_final(sessionmaker, await start(client))
    assert again.outcome == "insufficient_samples"

    sim.clear()
    assert await classify(client, "I want a cancellation") == "cancellation"


async def test_ac1_only_the_errors_that_fit_are_shown_but_all_are_rerun(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    account = ("my account is locked " * 200)[:4000]
    cancellation = ("cancellation of my plan " * 200)[:4000]
    await process_all(client, [account, cancellation])
    worker.start()

    review_id = await start(client)
    review = await wait_final(sessionmaker, review_id)

    assert review.outcome == "promoted"
    detail = (await client.get(f"/reviews/{review_id}")).json()
    assert all(p["base"]["in_error"] for p in detail["judgments"])
    assert (detail["base_score"], detail["candidate_score"]) == (2, 3)
    candidate = detail["candidate_prompt"]["content"]
    assert "cancellation" in candidate
    assert "account" not in candidate
    assert await calls(sessionmaker, review_id, "evaluate_candidate", "success") == 2
    assert await classify(client, "cancellation please") == "cancellation"
    assert await classify(client, "my account is locked") == "other"


# ------------------------------------------------------------------------------ AC-2


async def test_ac2_a_prompt_that_is_not_better_is_rejected(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("harmful_proposal")
    worker.start()

    review_id = await start(client)
    review = await wait_final(sessionmaker, review_id)

    assert review.outcome == "rejected"
    assert await scores(client, review_id) == (18, 12)
    versions = (await client.get("/prompts")).json()
    assert [(v["id"], v["status"]) for v in versions] == [(2, "rejected"), (1, "active")]

    again = await wait_final(sessionmaker, await start(client))
    assert again.outcome == "insufficient_samples"


async def test_ac2_a_tie_keeps_the_base_prompt(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    await process_all(
        client, [f"cancellation number {i}" for i in range(5)] + [f"hello {i}" for i in range(5)]
    )
    sim.fault("harmful_proposal")
    worker.start()

    review_id = await start(client)
    review = await wait_final(sessionmaker, review_id)

    assert review.outcome == "rejected"
    assert await scores(client, review_id) == (15, 15)
    versions = (await client.get("/prompts")).json()
    assert [(v["id"], v["status"]) for v in versions] == [(2, "rejected"), (1, "active")]


async def test_ac2_missing_candidate_outputs_score_zero_and_are_not_judged(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("delay", seconds=0.02)
    worker.start()
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
    sim.fault("schema_violation", model="fake")
    review = await wait_final(sessionmaker, review_id)

    assert review.outcome == "rejected"
    assert await scores(client, review_id) == (18, 0)
    assert await calls(sessionmaker, review_id, "judge") == 10


# ------------------------------------------------------------------------------ AC-3


async def test_ac3_no_samples_means_insufficient_samples_without_a_model_call(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    worker.start()
    review = await wait_final(sessionmaker, await start(client))

    assert review.outcome == "insufficient_samples"
    assert await scalar(sessionmaker, "SELECT count(*) FROM llm_calls") == 0


async def test_ac3_nothing_in_error_means_no_changes(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    await process_all(client, ["a billing question"])
    worker.start()
    review_id = await start(client)
    review = await wait_final(sessionmaker, review_id)

    assert review.outcome == "no_changes"
    assert await calls(sessionmaker, review_id, "judge") == 1
    assert await scalar(sessionmaker, "SELECT count(*) FROM prompt_versions") == 1


async def test_ac3_unjudgeable_outputs_are_not_in_error(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("schema_violation", model="fake-judge")
    worker.start()
    review_id = await start(client)
    review = await wait_final(sessionmaker, review_id)

    assert review.outcome == "no_changes"
    assert await calls(sessionmaker, review_id, "judge") == 60
    assert await calls(sessionmaker, review_id, "judge", "success") == 0
    assert (
        await scalar(
            sessionmaker,
            "SELECT count(*) FROM review_judgments WHERE review_id = :id "
            "AND expected_output IS NOT NULL AND json_type(expected_output) = 'null'",
            id=review_id,
        )
        == 10
    )
    assert await calls(sessionmaker, review_id, "improve_prompt") == 0
    assert await calls(sessionmaker, review_id, "evaluate_candidate") == 0


async def test_ac3_an_invalid_proposal_means_no_proposal(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("delay", seconds=0.02)
    worker.start()
    review_id = await start(client)

    async def base_judged() -> bool:
        return await judged(sessionmaker, review_id) == 10

    await wait_until(base_judged, what="the base judgments")
    sim.fault("malformed_json", model="fake-judge")
    review = await wait_final(sessionmaker, review_id)

    assert review.outcome == "no_proposal"
    assert await calls(sessionmaker, review_id, "improve_prompt") == 6
    assert await scalar(sessionmaker, "SELECT count(*) FROM prompt_versions") == 1
    assert await scalar(sessionmaker, "SELECT active_version_id FROM prompt_state") == 1


async def test_ac3_an_unknown_judge_model_fails_the_review_at_once(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    await process_all(client, TRAFFIC_A)
    review_id = await start(client)
    # The judge model is frozen at creation; set it to one the simulator does not know.
    await execute(
        sessionmaker, "UPDATE reviews SET judge_model = 'nope' WHERE id = :id", id=review_id
    )
    worker.start()
    review = await wait_final(sessionmaker, review_id)

    assert (review.status, review.error_code) == ("failed", "provider_misconfigured")
    assert await calls(sessionmaker, review_id, "judge") == 1
    assert (await client.post("/reviews")).status_code == 202


# ------------------------------------------------------------------------------ AC-4


async def test_ac4_a_killed_worker_continues_from_its_stored_results(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("delay", seconds=0.03)
    worker.start()
    review_id = await start(client)

    async def five_judged() -> bool:
        return await judged(sessionmaker, review_id) >= 5

    await wait_until(five_judged, what="5 judgments")
    await worker.kill()
    worker.start()

    await assert_ac1_result(client, sessionmaker, review_id)
    review = await wait_final(sessionmaker, review_id)
    assert review.attempts == 2
    assert (
        await scalar(
            sessionmaker,
            "SELECT count(*) FROM llm_calls WHERE review_id = :id AND operation = 'judge' "
            "AND error_code = 'interrupted'",
            id=review_id,
        )
        <= 1
    )


async def test_ac4_a_kill_during_the_rerun_keeps_the_candidate_and_its_outputs(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("delay", seconds=0.03)
    worker.start()
    review_id = await start(client)

    async def rerun_started() -> bool:
        return await calls(sessionmaker, review_id, "evaluate_candidate", "success") >= 3

    await wait_until(rerun_started, what="3 re-runs")
    await worker.kill()
    worker.start()

    await assert_ac1_result(client, sessionmaker, review_id)
    assert await calls(sessionmaker, review_id, "improve_prompt") == 1
    assert await scalar(sessionmaker, "SELECT count(*) FROM prompt_versions") == 2


async def test_ac4_four_kills_still_complete_the_review(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("delay", seconds=0.03)
    worker.start()
    review_id = await start(client)

    async def stored() -> int:
        return await scalar(
            sessionmaker,
            "SELECT (SELECT count(*) FROM review_judgments WHERE review_id = :id) "
            "+ (SELECT count(*) FROM review_judgments WHERE review_id = :id "
            "   AND expected_output IS NOT NULL) "
            "+ (SELECT count(*) FROM reviews WHERE id = :id AND candidate_prompt_id IS NOT NULL)",
            id=review_id,
        )

    for _ in range(4):
        before = await stored()

        async def one_more(before: int = before) -> bool:
            return await stored() > before

        await wait_until(one_more, what="one more result")
        await worker.kill()
        worker.start()

    await assert_ac1_result(client, sessionmaker, review_id)
    assert (await wait_final(sessionmaker, review_id)).attempts == 5


async def test_ac4_a_termination_signal_ends_the_attempt_as_terminated(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("delay", seconds=0.03)
    worker.start()
    review_id = await start(client)

    async def some_judged() -> bool:
        return await judged(sessionmaker, review_id) >= 3

    await wait_until(some_judged, what="3 judgments")
    assert await worker.terminate() == 0
    review = (await rows(sessionmaker, "SELECT * FROM reviews WHERE id = :id", id=review_id))[0]
    assert (review.status, review.error_code) == ("pending", "terminated")

    worker.start()
    await assert_ac1_result(client, sessionmaker, review_id)


async def test_ac4_two_workers_run_a_review_once(
    client: httpx.AsyncClient,
    sim: Sim,
    sessionmaker: async_sessionmaker,
    worker: Worker,
    migrated: Settings,
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("delay", seconds=0.01)
    second = Worker(migrated)
    worker.start()
    second.start()
    try:
        review_id = await start(client)
        await assert_ac1_result(client, sessionmaker, review_id)
        assert worker.running and second.running
        assert (await wait_final(sessionmaker, review_id)).attempts == 1
    finally:
        await second.close()


async def test_ac4_a_schema_newer_than_the_worker_sends_the_attempt_back(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("delay", seconds=0.03)
    worker.start()
    review_id = await start(client)

    async def some_judged() -> bool:
        return await judged(sessionmaker, review_id) >= 3

    await wait_until(some_judged, what="3 judgments")
    await execute(sessionmaker, "UPDATE alembic_version SET version_num = '9999'")

    assert await worker.wait_exit() == EXIT_SCHEMA_NEWER
    review = (await rows(sessionmaker, "SELECT * FROM reviews WHERE id = :id", id=review_id))[0]
    assert (review.status, review.error_code) == ("pending", "terminated")

    # The supervisor starts it again, on code that knows the new schema.
    await execute(sessionmaker, "UPDATE alembic_version SET version_num = :v", v=head_revision())
    worker.start()
    await assert_ac1_result(client, sessionmaker, review_id)


# ------------------------------------------------------------------------------ AC-5


async def test_ac5_an_outage_pauses_the_review_and_keeps_its_work(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("delay", seconds=0.1)
    worker.start()
    review_id = await start(client)

    async def five_judged() -> bool:
        return await judged(sessionmaker, review_id) >= 5

    await wait_until(five_judged, what="5 judgments")
    outage = sim.fault("5xx", model="fake-judge")

    async def paused() -> bool:
        status = await scalar(
            sessionmaker, "SELECT status FROM reviews WHERE id = :id", id=review_id
        )
        return status == "pending"

    await wait_until(paused, what="the attempt to end")
    review = (await rows(sessionmaker, "SELECT * FROM reviews WHERE id = :id", id=review_id))[0]
    assert review.error_code in ("circuit_open", "provider_unavailable")
    assert review.attempts == 1
    assert review.next_attempt_at is not None
    assert await judged(sessionmaker, review_id) == 5
    assert await classify(client, "a billing question") == "billing"

    sim.clear()
    del outage
    await assert_ac1_result(client, sessionmaker, review_id)
    assert (await wait_final(sessionmaker, review_id)).attempts == 2


async def test_ac5_an_outage_that_never_ends_expires_the_review(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("5xx", model="fake-judge")
    worker.start()
    review_id = await start(client)

    async def four_attempts() -> bool:
        return (
            await scalar(sessionmaker, "SELECT attempts FROM reviews WHERE id = :id", id=review_id)
            >= 4
        )

    await wait_until(four_attempts, what="4 attempts")
    status = await scalar(sessionmaker, "SELECT status FROM reviews WHERE id = :id", id=review_id)
    assert status in ("pending", "running")

    # Its time limit passes.
    await execute(
        sessionmaker,
        "UPDATE reviews SET expires_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = :id",
        id=review_id,
    )
    review = await wait_final(sessionmaker, review_id)
    assert (review.status, review.error_code) == ("failed", "review_expired")

    sim.clear()
    await asyncio.sleep(0.5)  # the worker's breaker for the judge closes again
    again = await start(client)
    await assert_ac1_result(client, sessionmaker, again)
    assert await judged(sessionmaker, again) == 20


async def test_a_call_that_outlasts_the_grace_period_is_cancelled(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, migrated: Settings
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("delay", seconds=5)
    worker = Worker(migrated.model_copy(update={"shutdown_grace_seconds": 0.3})).start()
    try:
        review_id = await start(client)

        async def in_flight() -> bool:
            return await calls(sessionmaker, review_id, "judge", "running") == 1

        await wait_until(in_flight, what="a judge call in flight")
        assert await worker.terminate() == 0
    finally:
        await worker.close()

    review = (await rows(sessionmaker, "SELECT * FROM reviews WHERE id = :id", id=review_id))[0]
    assert (review.status, review.error_code) == ("pending", "terminated")
    assert await calls(sessionmaker, review_id, "judge", "running") == 0
    assert (
        await scalar(
            sessionmaker,
            "SELECT error_code FROM llm_calls WHERE review_id = :id",
            id=review_id,
        )
        == "interrupted"
    )


async def test_a_worker_that_lost_its_lease_writes_nothing_more(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, worker: Worker
) -> None:
    await process_all(client, TRAFFIC_A)
    sim.fault("delay", seconds=0.03)
    worker.start()
    review_id = await start(client)

    async def some_judged() -> bool:
        return await judged(sessionmaker, review_id) >= 3

    await wait_until(some_judged, what="3 judgments")
    # Another worker took the review over; this one's next write finds the lease gone.
    await execute(
        sessionmaker, "UPDATE reviews SET owner_token = 'other' WHERE id = :id", id=review_id
    )
    stored = await judged(sessionmaker, review_id)
    await asyncio.sleep(0.3)
    assert await judged(sessionmaker, review_id) <= stored + 1  # at most the call in flight
    assert (
        await scalar(sessionmaker, "SELECT owner_token FROM reviews WHERE id = :id", id=review_id)
        == "other"
    )

    # The other owner's lease expires; this worker recovers the review and completes it.
    await assert_ac1_result(client, sessionmaker, review_id)
    assert (await wait_final(sessionmaker, review_id)).attempts == 2
