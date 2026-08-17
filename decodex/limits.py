"""Guard rails for a public, unauthenticated endpoint.

Analysis is CPU-bound and the engine is a shared single-threaded process, so the
service is only safe in the open if every request is bounded before it reaches
Stockfish. Three independent limits do that: a size cap on what can be parsed, a
depth cap on how much work one request may ask for, and a per-caller rate limit
on how often anyone may ask.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Tuple

# Work limits. Depth is the dominant cost: each extra ply roughly doubles the
# search, so the ceiling is what actually protects the CPU.
MAX_POSITION_DEPTH = 18
MAX_GAME_DEPTH = 12
MAX_PLIES = 160
MAX_MULTIPV = 5
MAX_SKILL = 20
MAX_BOT_MOVE_TIME = 1.0

# Input limits, applied before parsing so a hostile payload cannot cost anything.
MAX_FEN_CHARS = 120
MAX_MOVES_CHARS = 4000
MAX_PGN_CHARS = 24_000

# Rate limits per caller, in two tiers. Endpoints that run a search are the
# scarce resource; endpoints that only apply the rules of chess cost almost
# nothing, and throttling them at the same rate makes the board unusable.
HEAVY_BUCKET_CAPACITY = 12.0
HEAVY_REFILL_PER_SECOND = 0.5
CHEAP_BUCKET_CAPACITY = 90.0
CHEAP_REFILL_PER_SECOND = 8.0

# How long one request may hold the engine. A request that outlives this is
# abandoned rather than allowed to block the queue.
ANALYSIS_TIMEOUT_SECONDS = 60.0

# How many callers may queue for the engine before further requests are turned
# away. Without this a crowd simply grows the queue until everyone times out.
MAX_QUEUE_DEPTH = 8


class LimitExceeded(ValueError):
    """A request asked for more than the service is willing to do."""


def clamp_depth(value: int | None, ceiling: int, *, default: int) -> int:
    if value is None:
        return default
    if value < 1:
        raise LimitExceeded("depth must be at least 1")
    return min(value, ceiling)


def check_length(text: str, ceiling: int, label: str) -> str:
    if len(text) > ceiling:
        raise LimitExceeded(f"{label} is too long ({len(text)} > {ceiling} characters)")
    return text


@dataclass
class TokenBucket:
    tokens: float
    updated_at: float


@dataclass
class RateLimiter:
    """Token bucket per caller, with a bound on how many callers are tracked.

    The cap on tracked callers matters: an unbounded dict keyed by client address
    is itself a memory exhaustion vector on a public endpoint.
    """

    capacity: float = HEAVY_BUCKET_CAPACITY
    refill_per_second: float = HEAVY_REFILL_PER_SECOND
    max_tracked: int = 4096
    _buckets: Dict[str, TokenBucket] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def allow(self, caller: str, *, now: float | None = None) -> Tuple[bool, float]:
        """Consume one token. Returns whether it was allowed, and seconds to wait."""
        moment = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._buckets.get(caller)
            if bucket is None:
                if len(self._buckets) >= self.max_tracked:
                    self._evict(moment)
                bucket = TokenBucket(tokens=self.capacity, updated_at=moment)
                self._buckets[caller] = bucket

            elapsed = max(0.0, moment - bucket.updated_at)
            bucket.tokens = min(
                self.capacity, bucket.tokens + elapsed * self.refill_per_second
            )
            bucket.updated_at = moment

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True, 0.0
            missing = 1.0 - bucket.tokens
            return False, missing / self.refill_per_second

    def _evict(self, moment: float) -> None:
        """Drop the callers that have been idle longest.

        Called with the lock held. A caller whose bucket has refilled to capacity
        is indistinguishable from one that never called, so forgetting it costs
        nothing.
        """
        full_again = [
            caller
            for caller, bucket in self._buckets.items()
            if bucket.tokens + (moment - bucket.updated_at) * self.refill_per_second
            >= self.capacity
        ]
        for caller in full_again:
            del self._buckets[caller]
        if len(self._buckets) < self.max_tracked:
            return
        # Nothing was idle, so evict the oldest half by last use.
        by_age = sorted(self._buckets.items(), key=lambda item: item[1].updated_at)
        for caller, _ in by_age[: len(by_age) // 2]:
            del self._buckets[caller]
