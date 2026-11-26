"""The LLM gateway: the only way to a model (Processing NFR-5).

Timeouts, retries, the concurrency pools, the breakers and the call log sit here, above the
adapter. It is the only place that retries (Processing NFR-2).
"""

import asyncio
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker

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
            "process": asyncio.Semaphore(settings.process_concurrency)
        }
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

    def backoff(self, attempt: int) -> float:
        """The jittered wait after the given attempt: from the base, doubling each time."""
        base = self._settings.backoff_base_seconds * 2 ** (attempt - 1)
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
        deadline: float,
        pool: str = "process",
    ) -> CallOutcome:
        """Call the model until it answers validly, a failure is final, or the deadline.

        `deadline` is on the gateway's clock (monotonic). Raises a classified LlmFailure.
        """
        settings = self._settings
        breaker = self.breaker(profile.name, model)
        semaphore = self._pools[pool]
        adapter = self._adapter_for(profile)
        attempt = 0
        while True:
            attempt += 1
            if breaker.state is BreakerState.OPEN:
                breaker.before_attempt()  # raises CircuitOpen without waiting for a slot
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise DeadlineExceeded("deadline passed before an attempt")
            try:
                async with asyncio.timeout(remaining):
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
                    attempt,
                )
            finally:
                semaphore.release()

            if failure is None:
                assert result is not None
                return CallOutcome(
                    call_id=call_id,
                    output=result.output,
                    attempts=attempt,
                    duration_ms=duration_ms,
                    completed_at=completed_at,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    provider_request_id=result.provider_request_id,
                )

            if isinstance(failure, ProviderMisconfigured):
                failure.retry_after = settings.breaker_open_seconds
                raise failure
            if not isinstance(failure, RETRIED) or attempt >= settings.max_attempts:
                raise failure
            remaining = deadline - self._clock()
            if failure.retry_after is not None:
                # The server's Retry-After replaces the wait, as given (Processing NFR-2).
                if failure.retry_after >= remaining:
                    raise failure  # passed on to the caller (Processing FR-4)
                wait = failure.retry_after
            else:
                wait = self.backoff(attempt)
                if wait >= remaining:
                    raise DeadlineExceeded("no time left for another attempt") from failure
            await asyncio.sleep(wait)

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
        deadline: float,
        attempt: int,
    ) -> tuple[AdapterResult | None, LlmFailure | None, str, int, str]:
        call = new_call(ctx, provider=profile.name, model=model, attempt=attempt)
        try:
            async with self._sessionmaker() as session, session.begin():
                session.add(call)
        except BaseException:
            breaker.abandoned()
            raise

        remaining = deadline - self._clock()
        cut_by_deadline = remaining <= self._settings.attempt_timeout_seconds
        limit = max(0.0, min(self._settings.attempt_timeout_seconds, remaining))
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
        completed_at = now_iso()
        if failure is not None:
            async with self._sessionmaker() as session, session.begin():
                await close_call(
                    session,
                    call.id,
                    status=failure.call_status,
                    duration_ms=duration_ms,
                    completed_at=completed_at,
                    error_code=failure.code,
                    error_message=failure.detail[:200] or None,
                )
        return result, failure, call.id, duration_ms, completed_at
