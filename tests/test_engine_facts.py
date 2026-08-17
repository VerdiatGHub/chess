"""Engine-backed tests. These need a real Stockfish and are the ones that
prove the extracted facts are true rather than merely well-formatted.

Positions are chosen so the correct answer is forced, not a matter of taste.
"""

import chess
import chess.engine
import pytest

from decodex.facts import analyse_position, free_tempo_threat, hand_tempo
from decodex.game import Verdict, review_game
from decodex.report import render_game, render_position

pytestmark = pytest.mark.engine

SHALLOW = chess.engine.Limit(depth=10)


def test_eval_trace_agrees_with_the_actual_board(raw_engine, start_board):
    trace = raw_engine.eval_trace(start_board)
    parsed = {sq: pv.symbol for sq, pv in trace.piece_values.items()}
    actual = {
        chess.square_name(sq): piece.symbol()
        for sq, piece in start_board.piece_map().items()
    }
    assert parsed == actual


def test_starting_position_is_roughly_balanced(raw_engine, start_board):
    assert abs(raw_engine.eval_trace(start_board).final_cp) < 100


def test_eval_trace_reports_no_score_while_in_check(raw_engine):
    board = chess.Board("4k3/8/8/8/8/8/8/4KR2 b - - 0 1")
    board.push(chess.Move.from_uci("e8d8"))
    board.push(chess.Move.from_uci("f1f8"))
    assert board.is_check()
    trace = raw_engine.eval_trace(board)
    assert trace.in_check
    assert trace.final_cp is None


def test_lone_queen_is_the_most_important_piece(raw_engine):
    board = chess.Board("4k3/8/8/8/8/8/3Q4/4K3 w - - 0 1")
    white = raw_engine.eval_trace(board).for_color(chess.WHITE)
    assert white[0].square == "d2"
    assert white[0].symbol == "Q"


def test_mate_in_one_is_found_and_reported_as_mate(search_engine, raw_engine):
    # Back rank mate: Rd8#.
    board = chess.Board("6k1/5ppp/8/8/8/8/8/3R2K1 w - - 0 1")
    facts = analyse_position(
        board, search_engine, raw_engine, perspective=chess.WHITE, depth=12
    )
    best = facts.candidates[0]
    assert best.san == "Rd8#"
    assert best.is_mate
    assert best.mate == 1


def test_hand_tempo_only_flips_the_side_to_move():
    board = chess.Board("4k3/8/8/3q4/8/8/8/3RK3 b - - 0 1")
    handed = hand_tempo(board)
    assert handed.turn == chess.WHITE
    assert handed.piece_map() == board.piece_map()


def test_hand_tempo_discards_en_passant_rights():
    board = chess.Board()
    for uci in ("e2e4", "a7a6", "e4e5", "d7d5"):
        board.push(chess.Move.from_uci(uci))
    assert board.ep_square is not None
    assert hand_tempo(board).ep_square is None


def test_free_engine_move_is_recognised_as_a_threat(search_engine):
    # Black's queen on d5 is loose; White, given a tempo, simply takes it.
    board = chess.Board("4k3/8/8/3q4/8/8/8/3RK3 b - - 0 1")
    threat = free_tempo_threat(board, search_engine, SHALLOW)
    assert threat is not None
    assert threat.mover == chess.WHITE
    assert threat.free_tempo
    assert threat.san == "Rxd5"
    assert threat.captures == "queen"


def test_no_free_tempo_threat_is_invented_while_in_check(search_engine):
    board = chess.Board("4k3/8/8/8/8/8/8/4KR2 w - - 0 1")
    board.push(chess.Move.from_uci("f1f8"))
    assert board.is_check()
    assert free_tempo_threat(board, search_engine, SHALLOW) is None


def test_saving_a_hanging_queen_defuses_the_threat(search_engine, raw_engine):
    # Black to move with the queen loose on d5. Moving it away must show up as
    # both a threat before and a defusal after.
    board = chess.Board("4k3/8/8/3q4/8/8/8/3RK3 b - - 0 1")
    facts = analyse_position(
        board, search_engine, raw_engine, perspective=chess.BLACK, depth=12
    )
    assert facts.threat_before is not None
    assert facts.threat_before.san == "Rxd5"
    assert any("queen" in item and "d5" in item for item in facts.neutralised)


def test_perspective_of_the_side_not_to_move_uses_a_free_tempo(
    search_engine, raw_engine
):
    board = chess.Board()  # White to move.
    facts = analyse_position(
        board, search_engine, raw_engine, perspective=chess.BLACK, depth=10
    )
    assert facts.free_tempo_view
    assert facts.turn == chess.WHITE
    # Candidate moves must be Black's, so they come from black pieces.
    first = chess.Move.from_uci(facts.candidates[0].uci)
    assert hand_tempo(board).color_at(first.from_square) == chess.BLACK


def test_side_to_move_perspective_needs_no_free_tempo(search_engine, raw_engine):
    board = chess.Board()
    facts = analyse_position(
        board, search_engine, raw_engine, perspective=chess.WHITE, depth=10
    )
    assert not facts.free_tempo_view
    first = chess.Move.from_uci(facts.candidates[0].uci)
    assert board.color_at(first.from_square) == chess.WHITE


def test_candidates_are_ranked_in_the_mover_favour(search_engine, raw_engine):
    board = chess.Board()
    facts = analyse_position(
        board, search_engine, raw_engine, perspective=chess.WHITE, depth=12, multipv=3
    )
    assert len(facts.candidates) == 3
    scores = [c.cp_white for c in facts.candidates]
    assert scores == sorted(scores, reverse=True)


def test_perspective_of_a_side_whose_opponent_is_in_check_falls_back_to_threats(
    search_engine, raw_engine
):
    # White is in check, so Black cannot be handed a free tempo: the check has
    # to be answered first. Candidates must be withheld rather than invented.
    board = chess.Board("4k3/4q3/8/8/8/8/8/4K3 w - - 0 1")
    assert board.is_check()
    facts = analyse_position(
        board, search_engine, raw_engine, perspective=chess.BLACK, depth=10
    )
    assert facts.candidates == []
    assert facts.note is not None and "free tempo" in facts.note
    assert facts.threat_before is not None
    assert facts.threat_before.mover == chess.WHITE
    assert not facts.threat_before.free_tempo


def test_finished_game_is_reported_not_analysed(search_engine, raw_engine):
    board = chess.Board("7k/5QK1/8/8/8/8/8/8 b - - 0 1")
    assert board.is_checkmate()
    facts = analyse_position(
        board, search_engine, raw_engine, perspective=chess.BLACK, depth=8
    )
    assert facts.candidates == []
    assert facts.note is not None and "over" in facts.note


def test_position_report_mentions_every_section(search_engine, raw_engine):
    board = chess.Board("4k3/8/8/3q4/8/8/8/3RK3 b - - 0 1")
    facts = analyse_position(
        board, search_engine, raw_engine, perspective=chess.BLACK, depth=12
    )
    text = render_position(facts)
    for expected in ("Position analysis for Black", "Best moves", "Threats", "Piece importance"):
        assert expected in text


def test_scholars_mate_blunder_is_caught(search_engine):
    # 1.e4 e5 2.Bc4 Nc6 3.Qh5 Nf6?? 4.Qxf7# — Nf6 allows mate.
    moves_san = ["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"]
    board = chess.Board()
    moves = []
    for san in moves_san:
        move = board.parse_san(san)
        moves.append(move)
        board.push(move)

    review = review_game(chess.Board(), moves, search_engine, depth=12)
    assert review.result == "1-0"

    nf6 = next(m for m in review.moves if m.san == "Nf6")
    assert nf6.mover == chess.BLACK
    assert nf6.verdict is Verdict.BLUNDER
    assert nf6.loss_cp > 300
    assert nf6.allowed_mate

    # Black walked into mate, so their aggregates must be the worse of the two.
    # Accuracy is left out: White's Qh5 is judged an inaccuracy at some depths
    # and not at others, which makes an accuracy comparison depth-sensitive.
    assert review.average_loss(chess.BLACK) > review.average_loss(chess.WHITE)
    assert review.critical(chess.BLACK)[0].san == "Nf6"
    assert not any(m.verdict is Verdict.BLUNDER for m in review.for_side(chess.WHITE))


def test_delivering_mate_is_never_called_an_error(search_engine):
    moves_san = ["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"]
    board = chess.Board()
    moves = []
    for san in moves_san:
        move = board.parse_san(san)
        moves.append(move)
        board.push(move)
    review = review_game(chess.Board(), moves, search_engine, depth=12)
    mating = review.moves[-1]
    assert mating.san == "Qxf7#"
    assert not mating.verdict.is_error


def test_game_report_can_be_scoped_to_a_single_side(search_engine):
    moves = [
        chess.Move.from_uci(u) for u in ("e2e4", "e7e5", "g1f3", "b8c6")
    ]
    review = review_game(chess.Board(), moves, search_engine, depth=10)
    white_only = render_game(review, [chess.WHITE])
    assert "--- White ---" in white_only
    assert "--- Black ---" not in white_only

    both = render_game(review, [chess.WHITE, chess.BLACK])
    assert "--- White ---" in both and "--- Black ---" in both
