"""Processing acceptance criteria AC-1 to AC-5 (docs/specs/processing.md)."""

import asyncio
import logging
import time
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from tests.integration.conftest import Sim, ThreadServer

BILLING = "I have a problem with billing"


async def rows(sessionmaker: async_sessionmaker, sql: str, **params: Any) -> list[dict[str, Any]]:
    async with sessionmaker() as session:
        result = await session.execute(text(sql), params)
        return [dict(r._mapping) for r in result]


async def post(
    client: httpx.AsyncClient, message: str, *, key: str | None = None, rid: str | None = None
) -> httpx.Response:
    headers = {}
    if key is not None:
        headers["Idempotency-Key"] = key
    if rid is not None:
        headers["X-Request-ID"] = rid
    return await client.post("/process", json={"message": message}, headers=headers)


# --- AC-1 -------------------------------------------------------------------------------


async def test_ac1_a_message_becomes_a_validated_traceable_record(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        response = await post(client, BILLING, rid="ac1-trace")

    assert response.status_code == 200
    body = response.json()
    assert body["record"] == {"intent": "billing", "urgency": "normal"}
    assert body["prompt_version"] == 1
    assert body["request_id"] == "ac1-trace"
    assert response.headers["X-Request-ID"] == "ac1-trace"

    [sample] = await rows(sessionmaker, "SELECT * FROM samples")
    assert sample["id"] == body["sample_id"]
    assert sample["request_id"] == "ac1-trace"
    assert sample["input"] == BILLING
    assert sample["provider"] == "simulator" and sample["model"] == "fake"
    assert '"temperature": 0.0' in sample["model_config"]

    [call] = await rows(sessionmaker, "SELECT * FROM llm_calls")
    assert call["request_id"] == "ac1-trace"
    assert call["operation"] == "process"
    assert call["status"] == "success"
    assert call["sample_id"] == body["sample_id"]
    assert call["prompt_version_id"] == 1
    assert call["input_tokens"] > 0 and call["output_tokens"] > 0
    assert call["duration_ms"] is not None and call["completed_at"] is not None

    [line] = [r for r in caplog.records if r.name == "app.request"]
    assert line.__dict__["route"] == "/process"
    assert line.__dict__["status"] == 200
    assert line.__dict__["sample_id"] == body["sample_id"]
    assert line.__dict__["prompt_version"] == 1
    assert line.__dict__["idempotency"] == "none"
    for record in caplog.records:
        assert BILLING not in record.getMessage()
        assert all(BILLING not in str(v) for v in record.__dict__.values())


async def test_the_seeded_prompt_does_not_know_cancellation(client: httpx.AsyncClient) -> None:
    response = await post(client, "Please process my cancellation ASAP")

    assert response.json()["record"] == {"intent": "other", "urgency": "high"}


INVALID_REQUEST = {"code": "invalid_request", "message": "Invalid request", "retryable": False}
BAD_LENGTH = {**INVALID_REQUEST, "message": "message must be 1 to 4000 characters"}


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"message": ""}, BAD_LENGTH),
        ({"message": "x" * 4001}, BAD_LENGTH),
        ({}, INVALID_REQUEST),
        ({"message": 5}, INVALID_REQUEST),
        ({"message": "a", "extra": 1}, INVALID_REQUEST),
    ],
)
async def test_other_input_is_refused_before_any_model_call(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker,
    payload: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    response = await client.post("/process", json=payload)

    assert response.status_code == 422
    assert response.json() == expected
    assert await rows(sessionmaker, "SELECT id FROM llm_calls") == []


async def test_the_longest_allowed_message_is_accepted(client: httpx.AsyncClient) -> None:
    assert (await post(client, "x" * 4000)).status_code == 200


@pytest.mark.parametrize(
    "content",
    [b"{not json", b'["a list"]', b'"a string"', b"null"],
    ids=["malformed", "list", "string", "null"],
)
async def test_a_body_that_is_not_a_json_object_is_refused(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker, content: bytes
) -> None:
    response = await client.post(
        "/process", content=content, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json() == INVALID_REQUEST
    assert await rows(sessionmaker, "SELECT id FROM llm_calls") == []


@pytest.mark.parametrize("key", ["", "k" * 256], ids=["empty", "too-long"])
async def test_an_idempotency_key_out_of_bounds_is_refused_and_not_stored(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker, key: str
) -> None:
    response = await post(client, BILLING, key=key)

    assert response.status_code == 422
    assert response.json() == INVALID_REQUEST
    assert await rows(sessionmaker, "SELECT key FROM idempotency_requests") == []
    assert await rows(sessionmaker, "SELECT id FROM llm_calls") == []


async def test_the_longest_allowed_idempotency_key_is_accepted(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker
) -> None:
    response = await post(client, BILLING, key="k" * 255)

    assert response.status_code == 200
    [stored] = await rows(sessionmaker, "SELECT key FROM idempotency_requests")
    assert stored["key"] == "k" * 255


# --- AC-2 -------------------------------------------------------------------------------


async def test_ac2_a_retried_request_is_processed_once(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker
) -> None:
    first = await post(client, BILLING, key="key-1", rid="r1")
    # The same body, formatted differently, counts as the same request (FR-3).
    second = await client.post(
        "/process",
        content=b'{ "message" :  "I have a problem with billing" }',
        headers={
            "Idempotency-Key": "key-1",
            "X-Request-ID": "r2",
            "Content-Type": "application/json",
        },
    )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first.headers
    assert second.headers["X-Request-ID"] == "r2"
    assert len(await rows(sessionmaker, "SELECT id FROM samples")) == 1
    assert len(await rows(sessionmaker, "SELECT id FROM llm_calls")) == 1

    reused = await post(client, "a different message", key="key-1")

    assert reused.status_code == 422
    assert reused.json()["code"] == "idempotency_key_reused"
    assert len(await rows(sessionmaker, "SELECT id FROM llm_calls")) == 1


async def test_ac2_a_caller_that_disconnects_and_retries_gets_the_one_result(
    api_server: ThreadServer, sim: Sim, sessionmaker: async_sessionmaker
) -> None:
    sim.fault("delay", seconds=0.5)
    async with httpx.AsyncClient(base_url=api_server.url) as http:
        with pytest.raises(httpx.ReadTimeout):
            await http.post(
                "/process",
                json={"message": BILLING},
                headers={"Idempotency-Key": "key-2", "X-Request-ID": "gone"},
                timeout=0.1,
            )
        busy = await http.post(
            "/process", json={"message": BILLING}, headers={"Idempotency-Key": "key-2"}
        )
        assert busy.status_code == 409
        assert busy.json() == {
            "code": "request_in_progress",
            "message": "The request is in progress",
            "retryable": True,
        }
        assert int(busy.headers["Retry-After"]) >= 1

        await asyncio.sleep(0.8)
        done = await http.post(
            "/process", json={"message": BILLING}, headers={"Idempotency-Key": "key-2"}
        )

    assert done.status_code == 200
    assert done.headers["Idempotent-Replayed"] == "true"
    assert done.json()["request_id"] == "gone"
    assert done.json()["record"]["intent"] == "billing"
    assert len(await rows(sessionmaker, "SELECT id FROM samples WHERE request_id = 'gone'")) == 1
    assert len(await rows(sessionmaker, "SELECT id FROM llm_calls")) == 1


async def test_a_key_left_processing_by_a_dead_request_is_taken_over_once_its_lease_expires(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker
) -> None:
    from app.services.idempotency import request_hash

    async with sessionmaker() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO idempotency_requests (endpoint, key, request_hash, status, "
                "owner_token, lease_expires_at) VALUES ('/process', 'dead', :h, 'processing', "
                "'old-owner', :lease)"
            ),
            {"h": request_hash({"message": BILLING}), "lease": "2000-01-01T00:00:00.000Z"},
        )

    response = await post(client, BILLING, key="dead")

    assert response.status_code == 200
    [record] = await rows(sessionmaker, "SELECT * FROM idempotency_requests")
    assert record["status"] == "completed"
    assert record["sample_id"] == response.json()["sample_id"]


async def test_a_retryable_failure_lets_the_same_key_execute_again(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker
) -> None:
    sim.fault("5xx")
    failed = await post(client, BILLING, key="flaky")
    sim.clear()
    retried = await post(client, BILLING, key="flaky")

    assert failed.status_code == 503
    assert retried.status_code == 200
    assert "Idempotent-Replayed" not in retried.headers
    [record] = await rows(sessionmaker, "SELECT status FROM idempotency_requests")
    assert record["status"] == "completed"


async def test_a_rejection_is_stored_and_replayed(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker
) -> None:
    sim.fault("reject")
    first = await post(client, BILLING, key="bad")
    sim.clear()
    replay = await post(client, BILLING, key="bad")

    assert first.status_code == replay.status_code == 422
    assert replay.json() == first.json()
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert len(await rows(sessionmaker, "SELECT id FROM llm_calls")) == 1


# --- AC-3 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fault", "params", "status", "code", "attempts"),
    [
        ("5xx", {}, 503, "provider_unavailable", 3),
        ("schema_violation", {}, 502, "output_invalid", 3),
        ("never_answer", {}, 504, "deadline_exceeded", 3),
        ("429", {"retry_after": 30}, 503, "provider_unavailable", 1),
        ("reject", {}, 422, "provider_rejected", 1),
    ],
)
async def test_ac3_provider_failures_are_bounded_and_classified(
    client: httpx.AsyncClient,
    sim: Sim,
    sessionmaker: async_sessionmaker,
    migrated: Settings,
    fault: str,
    params: dict[str, Any],
    status: int,
    code: str,
    attempts: int,
) -> None:
    sim.fault(fault, **params)
    started = time.monotonic()
    response = await post(client, BILLING, rid=f"ac3-{fault}")
    elapsed = time.monotonic() - started

    assert response.status_code == status
    assert response.json()["code"] == code
    assert response.json()["retryable"] is (status != 422)
    assert set(response.json()) == {"code", "message", "retryable"}
    if fault == "429":
        assert response.headers["Retry-After"] == "30"
    elif status == 503:
        assert "Retry-After" in response.headers
    calls = await rows(sessionmaker, "SELECT * FROM llm_calls ORDER BY attempt")
    assert [c["attempt"] for c in calls] == list(range(1, attempts + 1))
    # An attempt with no answer in time is `timeout`; every other failure is `error`.
    expected_status = "timeout" if fault == "never_answer" else "error"
    assert [c["status"] for c in calls] == [expected_status] * attempts
    assert all(c["request_id"] == f"ac3-{fault}" for c in calls)
    assert await rows(sessionmaker, "SELECT id FROM samples") == []
    assert elapsed < migrated.request_deadline_seconds + 0.3


async def test_every_invalid_output_kind_is_a_502(client: httpx.AsyncClient, sim: Sim) -> None:
    for fault in ("malformed_json", "truncated"):
        sim.clear()
        sim.fault(fault)
        response = await post(client, BILLING)
        assert response.status_code == 502, fault
        assert response.json()["code"] == "output_invalid"


async def test_a_retry_after_that_fits_replaces_the_wait(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker
) -> None:
    sim.fault("429", retry_after=0.2)
    started = time.monotonic()
    response = await post(client, BILLING)
    elapsed = time.monotonic() - started

    assert response.status_code == 503
    assert len(await rows(sessionmaker, "SELECT id FROM llm_calls")) == 3
    assert elapsed >= 0.4  # two waits of the server's 0.2 s, not the 0.02 s backoff


@pytest.fixture
def missing_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIM_PROCESSING_MODEL", "not-installed")


async def test_a_model_that_is_not_installed_opens_the_breaker_at_once(
    missing_model: None,
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR):
        first = await post(client, BILLING)
    second = await post(client, BILLING)

    assert first.status_code == 503 and first.json()["code"] == "provider_misconfigured"
    assert "Retry-After" in first.headers
    assert any(r.getMessage() == "the configured model is not installed" for r in caplog.records)
    assert second.status_code == 503 and second.json()["code"] == "circuit_open"
    assert len(await rows(sessionmaker, "SELECT id FROM llm_calls")) == 1


# --- AC-4 -------------------------------------------------------------------------------


async def test_ac4_an_outage_fails_fast_and_recovers(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker, migrated: Settings
) -> None:
    sim.fault("5xx")
    while len(await rows(sessionmaker, "SELECT id FROM llm_calls")) < 5:
        response = await post(client, BILLING)
        assert response.status_code == 503

    started = time.monotonic()
    fast = await post(client, BILLING)
    assert time.monotonic() - started < 0.1
    assert fast.status_code == 503
    assert fast.json()["code"] == "circuit_open"
    assert "Retry-After" in fast.headers
    assert len(await rows(sessionmaker, "SELECT id FROM llm_calls")) == 5

    sim.clear()
    await asyncio.sleep(migrated.breaker_open_seconds)
    recovered = await post(client, BILLING)
    assert recovered.status_code == 200


async def test_ac4_overload_waits_for_a_slot_within_the_deadline(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker
) -> None:
    sim.fault("delay", seconds=0.3)
    responses = await asyncio.gather(*(post(client, f"{BILLING} {i}") for i in range(10)))

    statuses = [r.status_code for r in responses]
    assert set(statuses) <= {200, 504}
    assert 200 in statuses
    assert all(r.json()["code"] == "deadline_exceeded" for r in responses if r.status_code == 504)

    calls = await rows(
        sessionmaker,
        "SELECT created_at, completed_at FROM llm_calls WHERE operation = 'process'",
    )
    events = sorted(
        [(c["created_at"], 1) for c in calls] + [(c["completed_at"], -1) for c in calls],
        key=lambda e: (e[0], e[1]),  # an end before a start at the same instant
    )
    running = peak = 0
    for _, delta in events:
        running += delta
        peak = max(peak, running)
    assert peak <= 2


# --- AC-5 -------------------------------------------------------------------------------


async def test_ac5_health_checks_report_the_api_alone(
    client: httpx.AsyncClient, sim: Sim, sessionmaker: async_sessionmaker
) -> None:
    sim.fault("5xx")

    assert (await client.get("/healthz")).status_code == 200
    assert (await client.get("/readyz")).status_code == 200
    assert await rows(sessionmaker, "SELECT id FROM llm_calls") == []
