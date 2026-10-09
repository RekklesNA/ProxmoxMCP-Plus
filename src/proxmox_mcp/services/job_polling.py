"""Bounded, store-local polling coordination with persisted state checks."""

from __future__ import annotations

import threading
import time
import weakref
from collections import OrderedDict
from contextlib import contextmanager
from typing import Any, Iterator


class PollCoordinator:
    """Cache freshness only, never job data or authorization decisions."""

    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self._guard = threading.Lock()
        self._locks: weakref.WeakValueDictionary[str, Any] = weakref.WeakValueDictionary()
        self._fresh: OrderedDict[str, tuple[float, tuple[Any, ...]]] = OrderedDict()

    @contextmanager
    def serialize(self, job_id: str) -> Iterator[None]:
        with self._guard:
            lock = self._locks.get(job_id)
            if lock is None:
                lock = threading.RLock()
                self._locks[job_id] = lock
        with lock:
            yield

    @staticmethod
    def _fingerprint(record: Any) -> tuple[Any, ...]:
        return record.upid, record.node, record.status, record.updated_at, record.attempts

    def fresh(self, record: Any) -> bool:
        with self._guard:
            entry = self._fresh.get(record.job_id)
            return bool(entry and time.monotonic() - entry[0] < self.ttl
                        and entry[1] == self._fingerprint(record))

    def remember(self, record: Any) -> None:
        with self._guard:
            self._fresh[record.job_id] = (time.monotonic(), self._fingerprint(record))
            self._fresh.move_to_end(record.job_id)
            while len(self._fresh) > 500:
                self._fresh.popitem(last=False)

    def invalidate(self, job_id: str) -> None:
        with self._guard:
            self._fresh.pop(job_id, None)
