"""The gateway's review calls: the store hook and the stop event (Prompt Improvement FR-3)."""

import asyncio
import time
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.llm.adapter import AdapterResult, OllamaAdapter
from app.llm.call_log import CallContext
from app.llm.errors import ProviderUnavailable
from app.llm.gateway import CallOutcome, LlmGateway, Stopped
from app.llm.provider import Providers
from app.llm.schemas import TriageRecord
from app.services.reviews import LeaseLost, processing_model_settings
from tests.integration.conftest import Sim
from tests.integration.reviews_helpers import rows


def gateway_for(
    settings: Settings, sessionmaker: async_sessionmaker
) -> tuple[LlmGateway, Providers]:
    providers = Providers(settings)
    return LlmGateway(settings, sessionmaker, providers.adapter_for), providers


async def review_call(gateway: LlmGateway, settings: Settings, store, stop=None) -> None:  # noqa: ANN001
    await gateway.call_and_store(
        CallContext(operation="evaluate_candidate", request_id="r"),
        profile=settings.profiles()["simulator"],
        model="fake",
        prompt="billing",
        content="billing",
        output_schema=TriageRecord,
        model_settings=processing_model_settings(settings),
        store=store,
        stop=stop,
    )


async def test_a_store_that_raises_closes_its_call_as_an_error_with_its_code(
    migrated: Settings, sessionmaker: async_sessionmaker
) -> None:
    gateway, providers = gateway_for(migrated, sessionmaker)

    async def store(_session: AsyncSession, _result: CallOutcome | object) -> None:
        raise LeaseLost

    try:
        with pytest.raises(LeaseLost):
            await review_call(gateway, migrated, store)
    finally:
        await providers.aclose()
    calls = await rows(sessionmaker, "SELECT status, error_code FROM llm_calls")
    assert [tuple(c) for c in calls] == [("error", "lease_lost")]


async def test_a_stop_cuts_the_backoff_short(
    migrated: Settings, sim: Sim, sessionmaker: async_sessionmaker
) -> None:
    settings = migrated.model_copy(
        update={"review_backoff_base_seconds": 30.0, "review_backoff_max_seconds": 30.0}
    )
    gateway, providers = gateway_for(settings, sessionmaker)
    sim.fault("5xx")
    stop = asyncio.Event()

    async def store(_session: AsyncSession, _result: object) -> None:
        raise AssertionError("nothing to store")

    asyncio.get_running_loop().call_later(0.2, stop.set)
    started = time.monotonic()
    try:
        with pytest.raises(Stopped):
            await review_call(gateway, settings, store, stop)
    finally:
        await providers.aclose()
    assert time.monotonic() - started < 5
    assert await rows(sessionmaker, "SELECT count(*) FROM llm_calls") == [(1,)]


async def test_review_calls_get_their_own_attempts(
    migrated: Settings, sim: Sim, sessionmaker: async_sessionmaker
) -> None:
    settings = migrated.model_copy(
        update={
            "review_max_attempts": 4,
            "review_backoff_base_seconds": 0.001,
            "breaker_threshold": 99,
        }
    )
    gateway, providers = gateway_for(settings, sessionmaker)
    sim.fault("5xx")

    async def store(_session: AsyncSession, _result: object) -> None:
        raise AssertionError("nothing to store")

    try:
        with pytest.raises(ProviderUnavailable):
            await review_call(gateway, settings, store)
    finally:
        await providers.aclose()
    assert await rows(sessionmaker, "SELECT count(*) FROM llm_calls") == [(4,)]


async def test_a_store_that_raises_without_a_code_closes_its_call_as_store_failed(
    migrated: Settings, sessionmaker: async_sessionmaker
) -> None:
    gateway, providers = gateway_for(migrated, sessionmaker)

    async def store(_session: AsyncSession, _result: CallOutcome | object) -> None:
        raise RuntimeError("the result does not fit")

    try:
        with pytest.raises(RuntimeError):
            await review_call(gateway, migrated, store)
    finally:
        await providers.aclose()
    calls = await rows(sessionmaker, "SELECT status, error_code, error_message FROM llm_calls")
    assert [tuple(c) for c in calls] == [("error", "store_failed", "RuntimeError")]


async def test_a_store_that_raises_for_a_final_refusal_replaces_its_status_with_error(
    migrated: Settings, sim: Sim, sessionmaker: async_sessionmaker
) -> None:
    gateway, providers = gateway_for(migrated, sessionmaker)
    sim.fault("reject")
    stored: list[object] = []

    async def store(_session: AsyncSession, result: CallOutcome | object) -> None:
        stored.append(result)
        raise LeaseLost

    try:
        with pytest.raises(LeaseLost):
            await review_call(gateway, migrated, store)
    finally:
        await providers.aclose()
    # The refusal reached the store, but its call is not left as a recorded refusal.
    assert len(stored) == 1
    calls = await rows(sessionmaker, "SELECT status, error_code FROM llm_calls")
    assert [tuple(c) for c in calls] == [("error", "lease_lost")]


class BrokenOnNthCall(OllamaAdapter):
    """An adapter that delegates, except for one call that dies with something that is not
    a provider failure."""

    def __init__(self, base_url: str, fail_on: int) -> None:
        super().__init__(base_url)
        self._fail_on = fail_on
        self.calls = 0

    async def chat(self, **kwargs: Any) -> AdapterResult:
        self.calls += 1
        if self.calls == self._fail_on:
            raise RuntimeError("bug in the adapter")
        return await super().chat(**kwargs)


async def test_an_unexpected_error_in_a_half_open_trial_frees_the_trial(
    migrated: Settings, sim: Sim, sessionmaker: async_sessionmaker
) -> None:
    settings = migrated.model_copy(update={"breaker_threshold": 1, "review_max_attempts": 1})
    # Call 1 opens the breaker, call 2 is the half-open trial and dies, call 3 must run.
    adapter = BrokenOnNthCall(settings.profiles()["simulator"].base_url, 2)
    gateway = LlmGateway(settings, sessionmaker, lambda _profile: adapter)
    outcomes: list[object] = []

    async def store(_session: AsyncSession, result: CallOutcome | object) -> None:
        outcomes.append(result)

    try:
        sim.fault("5xx")
        with pytest.raises(ProviderUnavailable):
            await review_call(gateway, settings, store)
        assert gateway.breaker_states() == {"simulator/fake": "open"}
        sim.clear()
        await asyncio.sleep(settings.breaker_open_seconds + 0.1)

        with pytest.raises(RuntimeError, match="bug in the adapter"):
            await review_call(gateway, settings, store)
        # Without `abandoned()` the trial would stay in flight and this would be CircuitOpen.
        await review_call(gateway, settings, store)
    finally:
        await adapter.aclose()
    assert len(outcomes) == 1
    assert gateway.breaker_states() == {"simulator/fake": "closed"}
    statuses = [tuple(c) for c in await rows(sessionmaker, "SELECT status FROM llm_calls")]
    # The died trial's row stays `running`, to be closed as interrupted by recovery.
    assert sorted(statuses) == [("error",), ("running",), ("success",)]
