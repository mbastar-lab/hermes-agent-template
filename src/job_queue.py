"""FIFO serialization for agent jobs (ADR: serialize, one job at a time).

Every thread shares one /workspace checkout, so two concurrent /write runs would
race on git and on fixed-name research outputs. We run exactly one job at a time.
Callers `await queue.acquire()` to learn their position; when it's their turn the
returned context manager yields. Position lets the bot say "you're #2 in line".
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator


class FifoQueue:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # Number of jobs currently waiting OR running. Incremented on entry,
        # decremented on exit, so `pending_ahead` is accurate at enqueue time.
        self._depth = 0

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[int]:
        # How many jobs are ahead of this one right now (0 == runs immediately).
        ahead = self._depth
        self._depth += 1
        try:
            await self._lock.acquire()
            yield ahead
        finally:
            if self._lock.locked():
                self._lock.release()
            self._depth -= 1
