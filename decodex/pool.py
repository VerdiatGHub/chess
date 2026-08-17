"""A shared engine, borrowed one request at a time.

Stockfish is a single process holding a large NNUE network, so it is a shared
resource rather than something to spawn per request. Access is serialised behind
a semaphore with a bounded queue: under load, callers are turned away quickly
instead of all piling into a queue and timing out together.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Iterator, Optional, Tuple

import chess.engine

from .engine import RawEngine, find_engine
from .limits import ANALYSIS_TIMEOUT_SECONDS, MAX_QUEUE_DEPTH

# Two engine processes cost roughly 620 MB resident, which does not fit the
# 512 MB free tiers. In lean mode only the search engine runs, at the cost of
# the NNUE piece-importance panel, which is the one fact that needs Stockfish's
# non-standard `eval` command and therefore a second pipe.
LEAN_ENV_VAR = "DECODEX_LEAN"
LEAN_HASH_MB = 16
DEFAULT_HASH_MB = 128


def lean_mode_requested() -> bool:
    return os.environ.get(LEAN_ENV_VAR, "").strip().lower() in {"1", "true", "yes"}


class EngineBusy(RuntimeError):
    """Every slot is taken and the queue is full."""


class EnginePool:
    """One search engine, and an eval engine unless running lean.

    A single worker is correct here: the engine is configured for one thread, so
    two concurrent searches would contend for the same cores and make both slower
    than running them in turn.
    """

    def __init__(
        self,
        path: Optional[str] = None,
        *,
        threads: int = 1,
        hash_mb: Optional[int] = None,
        lean: Optional[bool] = None,
    ) -> None:
        self.path = find_engine(path)
        self.lean = lean_mode_requested() if lean is None else lean
        if hash_mb is None:
            hash_mb = LEAN_HASH_MB if self.lean else DEFAULT_HASH_MB

        self._search = chess.engine.SimpleEngine.popen_uci(self.path)
        self._search.configure({"Threads": threads, "Hash": hash_mb})
        self._raw = None if self.lean else RawEngine(self.path)
        self._lock = threading.Lock()
        self._waiting = threading.Semaphore(MAX_QUEUE_DEPTH)
        self._closed = False

    @contextmanager
    def borrow(self) -> Iterator[Tuple[chess.engine.SimpleEngine, Optional[RawEngine]]]:
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
            if self._raw is not None:
                self._raw.close()
            self._search.quit()
