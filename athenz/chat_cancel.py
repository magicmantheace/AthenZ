"""Owner-requested cooperative desktop reply cancellation.

Cancellation does not interrupt Ollama's in-flight HTTP request. It prevents an
uncommitted response being stored, and serialization with the commit protects
against a cancel/commit race. Nothing starts or cancels a coding task.
"""
from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from typing import Iterator


class ReplyCancelled(Exception):
    """Reply was discarded before conversation persistence."""


class ReplyCancelGate:
    """Single-use, thread-safe cancellation with a linearized commit boundary.

    request_cancel() takes the same lock as commit_guard(): a successful
    cancellation always precedes any later commit. If commit_guard has already
    started, the cancellation request waits and cannot retroactively undo the
    completed reply. Callers must never claim that this aborts model inference.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._cancelled = False
        self._committed = False

    def request_cancel(self) -> bool:
        """Return True when the pending reply was marked for discard."""
        with self._lock:
            if self._committed:
                return False
            self._cancelled = True
            return True

    def checkpoint(self) -> None:
        """Fail without changing the private database when canceled."""
        with self._lock:
            if self._cancelled:
                raise ReplyCancelled('Reply cancelled by the owner before it was stored')

    @contextmanager
    def commit_guard(self) -> Iterator[None]:
        """Keep cancel mutually exclusive with the entire SQLite transaction."""
        with self._lock:
            if self._cancelled:
                raise ReplyCancelled('Reply cancelled by the owner before it was stored')
            if self._committed:
                raise RuntimeError('A reply cancellation gate cannot be reused')
            yield
            self._committed = True
