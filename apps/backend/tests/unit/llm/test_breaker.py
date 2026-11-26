import pytest

from app.llm.breaker import BreakerState, CircuitBreaker
from app.llm.errors import CircuitOpen


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def make() -> tuple[CircuitBreaker, Clock]:
    clock = Clock()
    return CircuitBreaker(threshold=5, open_seconds=15, clock=clock), clock


def test_it_opens_after_five_attempts_in_a_row_without_an_answer() -> None:
    breaker, _ = make()
    for _ in range(4):
        breaker.before_attempt()
        breaker.no_answer()
    assert breaker.state is BreakerState.CLOSED
    breaker.no_answer()
    assert breaker.state is BreakerState.OPEN
    with pytest.raises(CircuitOpen) as exc:
        breaker.before_attempt()
    assert exc.value.retry_after == pytest.approx(15)


def test_any_answer_resets_the_count() -> None:
    breaker, _ = make()
    for _ in range(4):
        breaker.no_answer()
    breaker.answered()
    for _ in range(4):
        breaker.no_answer()
    assert breaker.state is BreakerState.CLOSED


def test_a_misconfigured_model_opens_it_at_once() -> None:
    breaker, _ = make()
    breaker.misconfigured()
    assert breaker.state is BreakerState.OPEN


def test_after_the_interval_one_trial_decides() -> None:
    breaker, clock = make()
    breaker.misconfigured()
    clock.now = 15.0
    assert breaker.state is BreakerState.HALF_OPEN

    breaker.before_attempt()  # the trial
    with pytest.raises(CircuitOpen):
        breaker.before_attempt()  # everyone else waits for it
    breaker.no_answer()
    assert breaker.state is BreakerState.OPEN

    clock.now = 30.0
    breaker.before_attempt()
    breaker.answered()
    assert breaker.state is BreakerState.CLOSED
    breaker.before_attempt()


def test_a_cancelled_trial_lets_another_one_through() -> None:
    breaker, clock = make()
    breaker.misconfigured()
    clock.now = 15.0
    breaker.before_attempt()
    breaker.abandoned()
    breaker.before_attempt()
