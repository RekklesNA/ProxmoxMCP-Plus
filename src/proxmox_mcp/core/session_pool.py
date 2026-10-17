"""Exclusive leases for independently authenticated Proxmox HTTP sessions."""

from __future__ import annotations

import time
from threading import Condition
from typing import Any, Callable


def close_sessions(sessions: list[Any]) -> None:
    """Attempt every close even if one transport fails during shutdown."""
    failure: BaseException | None = None
    while sessions:
        try:
            sessions.pop().close()
        except BaseException as exc:
            failure = failure or exc
    if failure is not None:
        raise failure


class SessionPool:
    """Bound concurrency without sharing mutable session or auth state.

    Closing rejects new leases, wakes waiters and waits for active requests
    before releasing sessions. Remote mutations are never automatically retried.
    """

    def __init__(self, sessions: list[Any], wait_timeout: float,
                 before_request: Callable[[], None], observe: Callable[[str, float, bool], None]) -> None:
        self._sessions = sessions
        self._available = list(sessions)
        self._condition = Condition()
        self._closed = False
        self._active = 0
        self._wait_timeout = wait_timeout
        self._before_request = before_request
        self._observe = observe

    def request(self, *args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        with self._condition:
            ready = self._condition.wait_for(
                lambda: self._closed or bool(self._available), timeout=self._wait_timeout,
            )
            if self._closed:
                raise RuntimeError("Proxmox session pool is closed")
            if not ready:
                self._observe("api_queue", (time.perf_counter() - start) * 1000, False)
                raise TimeoutError("Proxmox session pool is busy; retry later")
            session = self._available.pop()
            self._active += 1
        self._observe("api_queue", (time.perf_counter() - start) * 1000, True)
        start = time.perf_counter()
        success = False
        try:
            self._before_request()
            result = session.request(*args, **kwargs)
            success = getattr(result, "status_code", 200) < 400
            return result
        finally:
            with self._condition:
                self._available.append(session)
                self._active -= 1
                self._condition.notify_all()
            self._observe("api_request", (time.perf_counter() - start) * 1000, success)

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()
            self._condition.wait_for(lambda: self._active == 0)
        try:
            close_sessions(self._sessions)
        finally:
            self._sessions.clear()
            self._available.clear()
