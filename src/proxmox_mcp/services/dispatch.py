"""Bounded admission for per-target tool execution."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import anyio


class DispatchGate:
    """Limit active work and waiters; cancellation always releases admission."""

    def __init__(self, workers: int, queue_limit: int, queue_timeout: float) -> None:
        self._limiter = anyio.CapacityLimiter(workers)
        self._queue_limit = queue_limit
        self._queue_timeout = queue_timeout
        self._waiting = 0

    @asynccontextmanager
    async def acquire(self, metrics: Any, target: str) -> AsyncIterator[None]:
        start = time.perf_counter()
        acquired = False
        outcome = "error"
        try:
            try:
                self._limiter.acquire_nowait()
                acquired = True
            except anyio.WouldBlock:
                if self._waiting >= self._queue_limit:
                    raise RuntimeError("Tool dispatch queue is full; retry later") from None
                self._waiting += 1
                try:
                    with anyio.fail_after(self._queue_timeout):
                        await self._limiter.acquire()
                    acquired = True
                except TimeoutError:
                    raise RuntimeError("Tool dispatch queue timed out; retry later") from None
                finally:
                    self._waiting -= 1
            outcome = "success"
        finally:
            metrics.observe("dispatch_queue", (time.perf_counter() - start) * 1000,
                            acquired, target=target, outcome=outcome)
        try:
            yield
        finally:
            self._limiter.release()
