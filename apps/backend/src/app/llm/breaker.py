import time
from collections.abc import Callable
from enum import StrEnum

from app.llm.errors import CircuitOpen


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """One model's breaker (Processing NFR-3).

    It counts attempts that reached the model server: `no_answer` after one got no answer,
    `answered` after any answer at all. While open, `before_attempt` raises CircuitOpen; once
    the interval has passed, one trial attempt is let through and decides.
    """

    def __init__(
        self,
        threshold: int,
        open_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = threshold
        self._open_seconds = open_seconds
        self._clock = clock
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._trial_in_flight = False

    @property
    def state(self) -> BreakerState:
        if self._state is BreakerState.OPEN and self._remaining() <= 0:
            return BreakerState.HALF_OPEN
        return self._state

    def _remaining(self) -> float:
        return self._opened_at + self._open_seconds - self._clock()

    def before_attempt(self) -> None:
        if self._state is BreakerState.OPEN:
            remaining = self._remaining()
            if remaining > 0:
                raise CircuitOpen(retry_after=remaining)
            self._state = BreakerState.HALF_OPEN
            self._trial_in_flight = False
        if self._state is BreakerState.HALF_OPEN:
            if self._trial_in_flight:
                # Another call is the trial; it decides within one attempt's timeout.
                raise CircuitOpen(retry_after=1.0)
            self._trial_in_flight = True

    def answered(self) -> None:
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._trial_in_flight = False

    def no_answer(self) -> None:
        if self._state is BreakerState.HALF_OPEN:
            self._open()
            return
        self._failures += 1
        if self._failures >= self._threshold:
            self._open()

    def misconfigured(self) -> None:
        self._open()

    def abandoned(self) -> None:
        """The attempt ended without reaching a verdict (it was cancelled)."""
        if self._state is BreakerState.HALF_OPEN:
            self._trial_in_flight = False

    def _open(self) -> None:
        self._state = BreakerState.OPEN
        self._opened_at = self._clock()
        self._failures = 0
        self._trial_in_flight = False
