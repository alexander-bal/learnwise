"""When a termination signal arrived, so shutdown spends one grace period in all (FR-5)."""

import time

_requested_at: float | None = None


def mark_requested() -> None:
    global _requested_at
    if _requested_at is None:
        _requested_at = time.monotonic()


def remaining(grace_seconds: float) -> float:
    if _requested_at is None:
        return grace_seconds
    return max(0.0, grace_seconds - (time.monotonic() - _requested_at))
