import asyncio
import time
from collections.abc import Coroutine
from typing import Any


class TaskTracker:
    """Work that runs to its end even when the caller that awaits it goes away.

    A request's work runs in its own task, awaited through a shield, so a client disconnect
    does not cancel it (Processing FR-3). Shutdown waits for what is left (FR-5).
    """

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[Any]] = set()

    def __len__(self) -> int:
        return len(self._tasks)

    async def run[T](self, coro: Coroutine[Any, Any, T]) -> T:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return await asyncio.shield(task)

    async def drain(self, seconds: float) -> None:
        """Wait up to `seconds` for tracked work, then cancel what is left."""
        deadline = time.monotonic() + seconds
        while self._tasks:
            pending = list(self._tasks)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.wait(pending, timeout=remaining)
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
