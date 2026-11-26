import asyncio
import time

from app.core import shutdown
from app.core.tasks import TaskTracker


async def test_tracked_work_survives_its_caller_being_cancelled() -> None:
    tracker = TaskTracker()
    finished = asyncio.Event()

    async def work() -> str:
        await asyncio.sleep(0.05)
        finished.set()
        return "done"

    caller = asyncio.create_task(tracker.run(work()))
    await asyncio.sleep(0.01)
    caller.cancel()
    await asyncio.wait_for(finished.wait(), 1)
    assert finished.is_set()


async def test_drain_waits_for_work_then_cancels_what_is_left() -> None:
    tracker = TaskTracker()
    quick = asyncio.create_task(tracker.run(asyncio.sleep(0.01, "quick")))
    slow = asyncio.create_task(tracker.run(asyncio.sleep(10)))
    await asyncio.sleep(0)

    await tracker.drain(0.1)

    assert await quick == "quick"
    assert len(tracker) == 0
    slow.cancel()


def test_shutdown_spends_one_grace_period_from_the_signal(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(shutdown, "_requested_at", None)
    assert shutdown.remaining(25) == 25
    shutdown.mark_requested()
    assert 24 < shutdown.remaining(25) <= 25
    monkeypatch.setattr(shutdown, "_requested_at", time.monotonic() - 30)
    assert shutdown.remaining(25) == 0
