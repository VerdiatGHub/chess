"""A shared engine, borrowed one request at a time.

Stockfish is a single process holding a 133 MB network, so it is a shared
resource rather than something to spawn per request. Access is serialised behind
a semaphore with a bounded queue: under load, callers are turned away quickly
instead of all piling into a queue and timing out together.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator, Optional, Tuple

import chess.engine

from .engine import RawEngine, find_engine
from .limits import ANALYSIS_TIMEOUT_SECONDS, MAX_QUEUE_DEPTH


class EngineBusy(RuntimeError):
    """Every slot is taken and the queue is full."""


class EnginePool:
    """One search engine and one eval engine, lent out under a lock.

    A single worker is correct here: the engine is configured for one thread, so
    two concurrent searches would contend for the same cores and make both slower
    than running them in turn.
    """

    def __init__(self, path: Optional[str] = None, *, threads: int = 1, hash_mb: int = 128) -> None:
        self.path = find_engine(path)
        self._search = chess.engine.SimpleEngine.popen_uci(self.path)
        self._search.configure({"Threads": threads, "Hash": hash_mb})
        self._raw = RawEngine(self.path)
        self._lock = threading.Lock()
        self._waiting = threading.Semaphore(MAX_QUEUE_DEPTH)
        self._closed = False

    @contextmanager
    def borrow(self) -> Iterator[Tuple[chess.engine.SimpleEngine, RawEngine]]:
        if not self._waiting.acquire(blocking=False):
            raise EngineBusy("too many requests are already queued for analysis")
        try:
            if not self._lock.acquire(timeout=ANALYSIS_TIMEOUT_SECONDS):
                raise EngineBusy("analysis is taking too long; try again shortly")
            try:
                if self._closed:
                    raise EngineBusy("the engine is shutting down")
                yield self._search, self._raw
            finally:
                self._lock.release()
        finally:
            self._waiting.release()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._raw.close()
            self._search.quit()
