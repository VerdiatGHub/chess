"""Limits and guard rails. No engine, no server."""

import chess
import pytest

from decodex.limits import (
    MAX_GAME_DEPTH,
    MAX_POSITION_DEPTH,
    LimitExceeded,
    RateLimiter,
    check_length,
    clamp_depth,
)
from decodex.payload import game_payload
from decodex.game import GameReview, MoveReview, Verdict


def test_depth_is_clamped_to_the_ceiling():
    assert clamp_depth(99, MAX_POSITION_DEPTH, default=16) == MAX_POSITION_DEPTH
    assert clamp_depth(99, MAX_GAME_DEPTH, default=10) == MAX_GAME_DEPTH


def test_depth_falls_back_to_the_default_when_absent():
    assert clamp_depth(None, MAX_POSITION_DEPTH, default=16) == 16


def test_depth_below_one_is_rejected():
    # Nonsense rather than merely expensive, so it is an error not a clamp.
    with pytest.raises(LimitExceeded):
        clamp_depth(0, MAX_POSITION_DEPTH, default=16)


def test_a_depth_under_the_ceiling_is_honoured():
    assert clamp_depth(9, MAX_POSITION_DEPTH, default=16) == 9


def test_oversized_input_is_refused_before_parsing():
    with pytest.raises(LimitExceeded) as caught:
        check_length("x" * 200, 120, "FEN")
    assert "too long" in str(caught.value)
    assert check_length("short", 120, "FEN") == "short"


def test_bucket_allows_a_burst_then_refuses():
    limiter = RateLimiter(capacity=3, refill_per_second=1)
    assert [limiter.allow("a", now=0)[0] for _ in range(3)] == [True, True, True]
    allowed, wait = limiter.allow("a", now=0)
    assert not allowed
    assert wait == pytest.approx(1.0)


def test_bucket_refills_over_time():
    limiter = RateLimiter(capacity=2, refill_per_second=1)
    limiter.allow("a", now=0)
    limiter.allow("a", now=0)
    assert limiter.allow("a", now=0)[0] is False
    assert limiter.allow("a", now=1.0)[0] is True


def test_bucket_never_refills_past_capacity():
    limiter = RateLimiter(capacity=2, refill_per_second=1)
    limiter.allow("a", now=0)
    limiter.allow("a", now=0)
    # An hour later there should still be only two tokens, not 3600.
    assert [limiter.allow("a", now=3600)[0] for _ in range(3)] == [True, True, False]


def test_callers_are_limited_independently():
    limiter = RateLimiter(capacity=1, refill_per_second=1)
    assert limiter.allow("a", now=0)[0] is True
    assert limiter.allow("a", now=0)[0] is False
    assert limiter.allow("b", now=0)[0] is True


def test_tracked_callers_are_bounded():
    # An unbounded dict keyed by client address is a memory exhaustion vector.
    limiter = RateLimiter(capacity=2, refill_per_second=1, max_tracked=16)
    for index in range(200):
        limiter.allow(f"caller-{index}", now=index * 0.01)
    assert len(limiter._buckets) <= 16


def test_eviction_keeps_the_table_bounded_under_churn():
    # A stream of one-shot callers must not grow the table without limit.
    limiter = RateLimiter(capacity=1, refill_per_second=0.01, max_tracked=4)
    for index in range(200):
        limiter.allow(f"caller-{index}", now=index * 0.01)
    assert len(limiter._buckets) <= 4


def _move(ply, mover, verdict, loss=0, cp=25):
    return MoveReview(
        ply=ply,
        move_number=(ply + 1) // 2,
        mover=mover,
        san="Nf3",
        uci="g1f3",
        fen_before=chess.STARTING_FEN,
        best_san="Nf3",
        best_uci="g1f3",
        cp_before_white=cp,
        cp_after_white=cp,
        loss_cp=loss,
        verdict=verdict,
    )


def test_game_payload_is_json_ready():
    review = GameReview(
        moves=[
            _move(1, chess.WHITE, Verdict.BEST),
            _move(2, chess.BLACK, Verdict.BLUNDER, 900),
        ],
        result="1-0",
    )
    payload = game_payload(review, [chess.WHITE, chess.BLACK], {"White": "a", "Black": "b"})
    assert payload["result"] == "1-0"
    assert payload["white"] == "a"
    assert payload["graph"] == [25, 25]
    assert [side["side"] for side in payload["sides"]] == ["White", "Black"]
    assert payload["sides"][1]["breakdown"] == {"blunder": 1}

    import json

    # Nothing in the payload may be a chess.Color or an Enum, or the API breaks.
    json.dumps(payload)
