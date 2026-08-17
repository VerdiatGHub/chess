"""Move classification and game-level aggregation."""

import chess

from decodex.facts import MATE_SCORE
from decodex.game import (
    MAX_LOSS_CP,
    GameReview,
    MoveReview,
    Verdict,
    _loss_for_mover,
    classify,
    moves_from_uci,
)
from decodex.report import render_graph


def test_thresholds_map_loss_to_verdict():
    assert classify(0, was_only_move=False, played_best=True) is Verdict.BEST
    assert classify(5, was_only_move=False, played_best=False) is Verdict.EXCELLENT
    assert classify(30, was_only_move=False, played_best=False) is Verdict.GOOD
    assert classify(80, was_only_move=False, played_best=False) is Verdict.INACCURACY
    assert classify(200, was_only_move=False, played_best=False) is Verdict.MISTAKE
    assert classify(900, was_only_move=False, played_best=False) is Verdict.BLUNDER


def test_loss_is_capped_so_one_mate_cannot_dominate():
    # White missing a mate would otherwise register as a 1000-pawn loss.
    assert _loss_for_mover(chess.WHITE, MATE_SCORE, 0) == MAX_LOSS_CP
    assert _loss_for_mover(chess.BLACK, 0, MATE_SCORE) == MAX_LOSS_CP


def test_gaining_ground_is_never_a_loss():
    assert _loss_for_mover(chess.WHITE, 100, 400) == 0
    assert _loss_for_mover(chess.BLACK, -100, -400) == 0


def test_loss_is_measured_from_the_mover_side():
    # White drops 150 by ending up at -50 when +100 was available.
    assert _loss_for_mover(chess.WHITE, 100, -50) == 150
    # Black drops 150 by ending up at +50 when -100 was available.
    assert _loss_for_mover(chess.BLACK, -100, 50) == 150


def test_only_legal_move_is_never_blamed():
    assert classify(5000, was_only_move=True, played_best=False) is Verdict.FORCED


def test_only_the_bad_verdicts_count_as_errors():
    assert Verdict.BLUNDER.is_error
    assert Verdict.MISTAKE.is_error
    assert Verdict.INACCURACY.is_error
    assert not Verdict.GOOD.is_error
    assert not Verdict.BEST.is_error
    assert not Verdict.FORCED.is_error


def _move(ply, mover, verdict, loss=0):
    return MoveReview(
        ply=ply,
        move_number=(ply + 1) // 2,
        mover=mover,
        san="Nf3",
        uci="g1f3",
        fen_before=chess.STARTING_FEN,
        best_san="Nf3",
        best_uci="g1f3",
        cp_before_white=0,
        cp_after_white=0,
        loss_cp=loss,
        verdict=verdict,
    )


def test_allowed_mate_is_read_from_the_mover_side():
    white_mated = MoveReview(
        ply=1,
        move_number=1,
        mover=chess.WHITE,
        san="Kg1",
        uci="h1g1",
        fen_before=chess.STARTING_FEN,
        best_san="Kf1",
        best_uci="h1f1",
        cp_before_white=0,
        cp_after_white=-100000,
        loss_cp=1000,
        verdict=Verdict.BLUNDER,
        mate_after=-2,
    )
    assert white_mated.allowed_mate

    white_mating = MoveReview(
        ply=1,
        move_number=1,
        mover=chess.WHITE,
        san="Qf7",
        uci="h5f7",
        fen_before=chess.STARTING_FEN,
        best_san="Qf7",
        best_uci="h5f7",
        cp_before_white=100000,
        cp_after_white=100000,
        loss_cp=0,
        verdict=Verdict.BEST,
        mate_after=1,
    )
    assert not white_mating.allowed_mate


def test_no_mate_information_means_no_mate_claim():
    assert not _move(1, chess.WHITE, Verdict.BEST).allowed_mate


def _review():
    return GameReview(
        moves=[
            _move(1, chess.WHITE, Verdict.BEST),
            _move(2, chess.BLACK, Verdict.BLUNDER, 900),
            _move(3, chess.WHITE, Verdict.GOOD, 30),
            _move(4, chess.BLACK, Verdict.MISTAKE, 200),
            _move(5, chess.WHITE, Verdict.FORCED, 4000),
        ],
        result="1-0",
    )


def test_side_filter_splits_the_two_players():
    review = _review()
    assert len(review.for_side(chess.WHITE)) == 3
    assert len(review.for_side(chess.BLACK)) == 2
    assert len(review.for_side(None)) == 5


def test_accuracy_ignores_forced_moves():
    review = _review()
    # White: best and good count as clean, the forced move is excluded entirely.
    assert review.accuracy(chess.WHITE) == 100.0
    assert review.accuracy(chess.BLACK) == 0.0


def test_average_loss_excludes_forced_moves():
    review = _review()
    # Without the exclusion the forced 40.00 would swamp this.
    assert review.average_loss(chess.WHITE) == 15.0
    assert review.average_loss(chess.BLACK) == 550.0


def test_critical_moments_are_the_worst_errors_first():
    review = _review()
    critical = review.critical(None)
    assert [m.loss_cp for m in critical] == [900, 200]


def test_critical_moments_can_be_scoped_to_one_side():
    review = _review()
    assert review.critical(chess.WHITE) == []
    assert [m.loss_cp for m in review.critical(chess.BLACK)] == [900, 200]


def test_accuracy_is_undefined_when_nothing_is_reviewable():
    review = GameReview(moves=[_move(1, chess.WHITE, Verdict.FORCED, 10)])
    assert review.accuracy(chess.WHITE) is None
    assert review.average_loss(chess.WHITE) is None


def _best_move(ply, mover, *, second_best_cp, cp_before=50, legal_count=30):
    return MoveReview(
        ply=ply,
        move_number=(ply + 1) // 2,
        mover=mover,
        san="Bxd4",
        uci="e3d4",
        fen_before=chess.STARTING_FEN,
        best_san="Bxd4",
        best_uci="e3d4",
        cp_before_white=cp_before,
        cp_after_white=cp_before,
        loss_cp=0,
        verdict=Verdict.BEST,
        legal_count=legal_count,
        second_best_cp_white=second_best_cp,
        second_best_san="Qxd4",
    )


def test_swing_measures_the_gap_to_the_second_choice():
    # White at +0.50 with the alternative at -0.35 gained 0.85 by finding it.
    white = _best_move(1, chess.WHITE, cp_before=50, second_best_cp=-35)
    assert white.swing_cp == 85
    # Black's sign is the other way round.
    black = _best_move(2, chess.BLACK, cp_before=-50, second_best_cp=35)
    assert black.swing_cp == 85


def test_swing_is_zero_without_a_searched_alternative():
    assert _move(1, chess.WHITE, Verdict.BEST).swing_cp == 0


def test_good_moves_need_a_real_choice_and_a_real_gap():
    obvious = _best_move(1, chess.WHITE, second_best_cp=45)
    forced = _best_move(3, chess.WHITE, second_best_cp=-300, legal_count=2)
    earned = _best_move(5, chess.WHITE, second_best_cp=-35)
    review = GameReview(moves=[obvious, forced, earned])
    assert review.good_moves(chess.WHITE) == [earned]


def test_good_moves_ignore_an_already_decided_position():
    # Best play in a position that is already won says nothing about the player.
    won = _best_move(1, chess.WHITE, cp_before=5000, second_best_cp=3000)
    assert GameReview(moves=[won]).good_moves(chess.WHITE) == []


def test_good_moves_come_hardest_first():
    small = _best_move(1, chess.WHITE, second_best_cp=-20)
    large = _best_move(3, chess.WHITE, second_best_cp=-200)
    review = GameReview(moves=[small, large])
    assert review.good_moves(chess.WHITE) == [large, small]


def test_graph_is_empty_without_moves():
    assert render_graph(GameReview()) == []


def test_graph_draws_one_block_per_move():
    review = GameReview(
        moves=[
            _move(1, chess.WHITE, Verdict.BEST),
            _move(2, chess.BLACK, Verdict.BEST),
            _move(3, chess.WHITE, Verdict.BEST),
        ]
    )
    bars = render_graph(review)[0].split()[-1]
    assert len(bars) == 3


def test_graph_scales_to_the_game_it_draws():
    quiet = GameReview(moves=[_scored_move(1, 10), _scored_move(2, -10)])
    wild = GameReview(moves=[_scored_move(1, 600), _scored_move(2, -600)])
    # A half-pawn game should not look like a collapse, and a decided game
    # should not flatten: both use the full block range, at different scales.
    assert "full height is 1.00" in render_graph(quiet)[1]
    assert "full height is 5.00" in render_graph(wild)[1]


def test_graph_samples_long_games_down_to_the_width():
    review = GameReview(moves=[_scored_move(i, i * 10) for i in range(1, 200)])
    bars = render_graph(review, width=40)[0].split()[-1]
    assert len(bars) == 40


def _scored_move(ply, cp_after):
    return MoveReview(
        ply=ply,
        move_number=(ply + 1) // 2,
        mover=chess.WHITE if ply % 2 else chess.BLACK,
        san="Nf3",
        uci="g1f3",
        fen_before=chess.STARTING_FEN,
        best_san="Nf3",
        best_uci="g1f3",
        cp_before_white=cp_after,
        cp_after_white=cp_after,
        loss_cp=0,
        verdict=Verdict.BEST,
    )


def test_moves_accepts_both_uci_and_san():
    board = chess.Board()
    assert [m.uci() for m in moves_from_uci(board, ["e2e4", "e7e5"])] == [
        "e2e4",
        "e7e5",
    ]
    assert [m.uci() for m in moves_from_uci(board, ["e4", "e5", "Nf3"])] == [
        "e2e4",
        "e7e5",
        "g1f3",
    ]


def test_parsing_moves_does_not_disturb_the_caller_board():
    board = chess.Board()
    moves_from_uci(board, ["e2e4", "e7e5"])
    assert board.fen() == chess.STARTING_FEN
