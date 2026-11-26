import random

from app.core.config import Settings
from app.llm.gateway import LlmGateway


def test_the_review_backoff_doubles_from_2_seconds_up_to_60() -> None:
    gateway = LlmGateway(Settings(), None, lambda _p: None, rng=random.Random(1))  # ty: ignore[invalid-argument-type]
    policy = gateway.review_policy
    for attempt, base in ((1, 2), (2, 4), (5, 32), (6, 60), (9, 60)):
        wait = gateway.backoff(attempt, policy)
        assert base / 2 <= wait <= base


def test_the_process_backoff_has_no_cap() -> None:
    gateway = LlmGateway(Settings(), None, lambda _p: None, rng=random.Random(1))  # ty: ignore[invalid-argument-type]
    assert gateway.backoff(10) >= 0.5 * 2**9 / 2
