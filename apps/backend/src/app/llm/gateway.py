"""The LLM gateway: the only way to a model (Processing NFR-5).

Timeouts, retries, the concurrency pools, the breakers and the call log sit here, above the
adapter. It is the only place that retries (Processing NFR-2).
"""

import asyncio
import contextlib
import logging
import math
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import ProviderProfile, Settings
from app.db.time import now_iso
from app.llm.adapter import AdapterResult, ModelSettings, OllamaAdapter
from app.llm.breaker import BreakerState, CircuitBreaker
from app.llm.call_log import CallContext, close_call, new_call
from app.llm.errors import (
    AttemptTimedOut,
    DeadlineExceeded,
    LlmFailure,
    OutputInvalid,
    ProviderMisconfigured,
    ProviderRejected,
    ProviderUnavailable,
)

log = logging.getLogger(__name__)

RETRIED = (ProviderUnavailable, OutputInvalid)
# Failures a review stores as its result rather than ending its attempt on (Prompt
# Improvement FR-2): with a `store` hook they are stored with the close of their call.
STORED_FAILURES = (OutputInvalid, ProviderRejected)


class Stopped(Exception):
    """The caller's stop event was set between two attempts of a call."""


@dataclass(frozen=True)
class CallPolicy:
    """How many attempts a call gets, how long each, and the waits between them."""

    pool: str
    max_attempts: int
    attempt_timeout: float
    backoff_base: float
    backoff_cap: float | None = None


@dataclass(frozen=True)
class CallOutcome:
    """A successful call. Its llm_calls row is still `running`: the caller closes it with
    these values in the transaction that stores the result (Processing FR-1)."""

    call_id: str
    output: BaseModel
    attempts: int
    duration_ms: int
    completed_at: str
    input_tokens: int | None
    output_tokens: int | None
    provider_request_id: str | None


# Stores a call's result in the transaction that closes the call (Prompt Improvement FR-3).
# It is given the CallOutcome of a success, or the final failure of STORED_FAILURES.
StoreResult = Callable[[AsyncSession, CallOutcome | LlmFailure], Awaitable[None]]


class LlmGateway:
    def __init__(
        self,
        settings: Settings,
        write_sessionmaker: async_sessionmaker,
        adapter_for: Callable[[ProviderProfile], OllamaAdapter],
        *,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self._settings = settings
        self._sessionmaker = write_sessionmaker
        self._adapter_for = adapter_for
        self._clock = clock
        self._rng = rng or random.Random()
        # Pools and breakers are per process (Processing NFR-3).
        self._pools: dict[str, asyncio.Semaphore] = {
            "process": asyncio.Semaphore(settings.process_concurrency),
            # Review calls never take a slot of /process (Prompt Improvement NFR-1).
            "review": asyncio.Semaphore(settings.review_concurrency),
        }
        self.process_policy = CallPolicy(
            pool="process",
            max_attempts=settings.max_attempts,
            attempt_timeout=settings.attempt_timeout_seconds,
            backoff_base=settings.backoff_base_seconds,
        )
        self.review_policy = CallPolicy(
            pool="review",
            max_attempts=settings.review_max_attempts,
            attempt_timeout=settings.review_attempt_timeout_seconds,
            backoff_base=settings.review_backoff_base_seconds,
            backoff_cap=settings.review_backoff_max_seconds,
        )
        self._breakers: dict[tuple[str, str], CircuitBreaker] = {}

    def breaker(self, provider: str, model: str) -> CircuitBreaker:
        key = (provider, model)
        if key not in self._breakers:
            self._breakers[key] = CircuitBreaker(
                self._settings.breaker_threshold, self._settings.breaker_open_seconds, self._clock
            )
        return self._breakers[key]

    def breaker_states(self) -> dict[str, str]:
        return {f"{p}/{m}": b.state.value for (p, m), b in self._breakers.items()}

    def backoff(self, attempt: int, policy: CallPolicy | None = None) -> float:
        """The jittered wait after the given attempt: from the base, doubling each time."""
        policy = policy or self.process_policy
        base = policy.backoff_base * 2 ** (attempt - 1)
        if policy.backoff_cap is not None:
            base = min(base, policy.backoff_cap)
        return base / 2 + self._rng.uniform(0, base / 2)

    async def call(
        self,
        ctx: CallContext,
        *,
        profile: ProviderProfile,
        model: str,
        prompt: str,
        content: str,
        output_schema: type[BaseModel],
        model_settings: ModelSettings,
        deadline: float | None,
        policy: CallPolicy | None = None,
        stop: asyncio.Event | None = None,
    ) -> CallOutcome:
        """Call the model until it answers validly, a failure is final, or the deadline.

        `deadline` is on the gateway's clock (monotonic), or None for no deadline. Raises a
        classified LlmFailure, or Stopped when `stop` is set between attempts.
        """
        outcome = await self._run(
            ctx,
            profile=profile,
            model=model,
            prompt=prompt,
            content=content,
            output_schema=output_schema,
            model_settings=model_settings,
            deadline=deadline,
            policy=policy or self.process_policy,
            stop=stop,
            store=None,
        )
        assert outcome is not None
        return outcome

    async def call_and_store(
        self,
        ctx: CallContext,
        *,
        profile: ProviderProfile,
        model: str,
        prompt: str,
        content: str,
        output_schema: type[BaseModel],
        model_settings: ModelSettings,
        store: StoreResult,
        policy: CallPolicy | None = None,
        stop: asyncio.Event | None = None,
    ) -> None:
        """A call with no deadline whose result `store` writes in the transaction that closes
        it: a success, or a final OutputInvalid or ProviderRejected. Any other failure is
        raised, as is whatever `store` raises (the call is then closed as an error)."""
        await self._run(
            ctx,
            profile=profile,
            model=model,
            prompt=prompt,
            content=content,
            output_schema=output_schema,
            model_settings=model_settings,
            deadline=None,
            policy=policy or self.review_policy,
            stop=stop,
            store=store,
        )

    async def _run(
        self,
        ctx: CallContext,
        *,
        profile: ProviderProfile,
        model: str,
        prompt: str,
        content: str,
        output_schema: type[BaseModel],
        model_settings: ModelSettings,
        deadline: float | None,
        policy: CallPolicy,
        stop: asyncio.Event | None,
        store: StoreResult | None,
    ) -> CallOutcome | None:
        settings = self._settings
        breaker = self.breaker(profile.name, model)
        semaphore = self._pools[policy.pool]
        adapter = self._adapter_for(profile)
        attempt = 0
        while True:
            attempt += 1
            if stop is not None and stop.is_set():
                raise Stopped
            if breaker.state is BreakerState.OPEN:
                breaker.before_attempt()  # raises CircuitOpen without waiting for a slot
            remaining = self._remaining(deadline)
            if remaining <= 0:
                raise DeadlineExceeded("deadline passed before an attempt")
            try:
                async with asyncio.timeout(remaining if deadline is not None else None):
                    await semaphore.acquire()
            except TimeoutError:
                # Never reached the model server, so the breaker does not count it.
                raise DeadlineExceeded("no slot before the deadline") from None
            try:
                breaker.before_attempt()
                result, failure, call_id, duration_ms, completed_at = await self._attempt(
                    ctx,
                    adapter,
                    breaker,
                    profile,
                    model,
                    prompt,
                    content,
                    output_schema,
                    model_settings,
                    deadline,
                    policy,
                    attempt,
                )
            finally:
                semaphore.release()

            if failure is None:
                assert result is not None
                outcome = CallOutcome(
                    call_id=call_id,
                    output=result.output,
                    attempts=attempt,
                    duration_ms=duration_ms,
                    completed_at=completed_at,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    provider_request_id=result.provider_request_id,
                )
                if store is None:
                    return outcome
                await self._store(store, outcome, call_id, duration_ms, completed_at)
                return None

            final = not isinstance(failure, RETRIED) or attempt >= policy.max_attempts
            if store is not None and final and isinstance(failure, STORED_FAILURES):
                await self._store(store, failure, call_id, duration_ms, completed_at)
                return None
            await self._close_failure(call_id, failure, duration_ms, completed_at)

            if isinstance(failure, ProviderMisconfigured):
                failure.retry_after = settings.breaker_open_seconds
                raise failure
            if final:
                raise failure
            remaining = self._remaining(deadline)
            if failure.retry_after is not None:
                # The server's Retry-After replaces the wait, as given (Processing NFR-2).
                if failure.retry_after >= remaining:
                    raise failure  # passed on to the caller (Processing FR-4)
                wait = failure.retry_after
            else:
                wait = self.backoff(attempt, policy)
                if wait >= remaining:
                    raise DeadlineExceeded("no time left for another attempt") from failure
            await self._sleep(wait, stop)

    def _remaining(self, deadline: float | None) -> float:
        return math.inf if deadline is None else deadline - self._clock()

    @staticmethod
    async def _sleep(seconds: float, stop: asyncio.Event | None) -> None:
        if stop is None:
            await asyncio.sleep(seconds)
            return
        # A stop does not wait out the backoff: there is no call in flight to finish.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        if stop.is_set():
            raise Stopped

    async def _store(
        self,
        store: StoreResult,
        result: CallOutcome | LlmFailure,
        call_id: str,
        duration_ms: int,
        completed_at: str,
    ) -> None:
        try:
            async with self._sessionmaker() as session, session.begin():
                if isinstance(result, CallOutcome):
                    await close_call(
                        session,
                        call_id,
                        status="success",
                        duration_ms=duration_ms,
                        completed_at=completed_at,
                        input_tokens=result.input_tokens,
                        output_tokens=result.output_tokens,
                        provider_request_id=result.provider_request_id,
                    )
                else:
                    await close_call(
                        session,
                        call_id,
                        status=result.call_status,
                        duration_ms=duration_ms,
                        completed_at=completed_at,
                        error_code=result.code,
                        error_message=result.detail[:200] or None,
                    )
                await store(session, result)
        except Exception as exc:
            # The result was not stored, so its call did not produce one.
            code = getattr(exc, "code", None)
            async with self._sessionmaker() as session, session.begin():
                await close_call(
                    session,
                    call_id,
                    status="error",
                    duration_ms=duration_ms,
                    completed_at=completed_at,
                    error_code=code if isinstance(code, str) else "store_failed",
                    error_message=type(exc).__name__,
                )
            raise

    async def _close_failure(
        self, call_id: str, failure: LlmFailure, duration_ms: int, completed_at: str
    ) -> None:
        async with self._sessionmaker() as session, session.begin():
            await close_call(
                session,
                call_id,
                status=failure.call_status,
                duration_ms=duration_ms,
                completed_at=completed_at,
                error_code=failure.code,
                error_message=failure.detail[:200] or None,
            )

    async def _attempt(
        self,
        ctx: CallContext,
        adapter: OllamaAdapter,
        breaker: CircuitBreaker,
        profile: ProviderProfile,
        model: str,
        prompt: str,
        content: str,
        output_schema: type[BaseModel],
        model_settings: ModelSettings,
        deadline: float | None,
        policy: CallPolicy,
        attempt: int,
    ) -> tuple[AdapterResult | None, LlmFailure | None, str, int, str]:
        """One attempt. Its row is left `running`; the caller closes it."""
        call = new_call(ctx, provider=profile.name, model=model, attempt=attempt)
        try:
            async with self._sessionmaker() as session, session.begin():
                session.add(call)
        except BaseException:
            breaker.abandoned()
            raise

        remaining = self._remaining(deadline)
        cut_by_deadline = remaining <= policy.attempt_timeout
        limit = max(0.0, min(policy.attempt_timeout, remaining))
        started = self._clock()
        result: AdapterResult | None = None
        failure: LlmFailure | None = None
        try:
            # The timeout starts here, when the call leaves the service; cancelling the
            # request on timeout closes its connection (Processing NFR-2).
            async with asyncio.timeout(limit):
                result = await adapter.chat(
                    model=model,
                    prompt=prompt,
                    content=content,
                    output_schema=output_schema,
                    settings=model_settings,
                )
        except TimeoutError:
            breaker.no_answer()
            failure = (
                DeadlineExceeded("attempt cut short by the request deadline")
                if cut_by_deadline
                else AttemptTimedOut(f"no answer in {limit:.1f}s")
            )
        except ProviderMisconfigured as exc:
            breaker.misconfigured()
            failure = exc
            log.error(
                "the configured model is not installed",
                extra={"provider": profile.name, "model": model},
            )
        except ProviderUnavailable as exc:
            breaker.no_answer()
            failure = exc
        except (OutputInvalid, ProviderRejected) as exc:
            breaker.answered()
            failure = exc
        except BaseException:
            # Cancelled: the row stays `running` and is closed as interrupted later.
            breaker.abandoned()
            raise
        else:
            breaker.answered()

        duration_ms = round((self._clock() - started) * 1000)
        return result, failure, call.id, duration_ms, now_iso()
