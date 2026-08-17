"""Parsing Stockfish's `eval` output, exercised against captured real output."""

import chess

from decodex.engine import parse_eval_trace

# Trimmed from `stockfish eval` after 1.e4 e5 2.Nf3 Nc6 3.Bb5.
SAMPLE = """
 NNUE derived piece values:
+-------+-------+-------+-------+-------+-------+-------+-------+
|   r   |       |   b   |   q   |   k   |   b   |   n   |   r   |
| -5.35 |       | -4.73 | -8.35 |       | -4.34 | -4.07 | -5.45 |
+-------+-------+-------+-------+-------+-------+-------+-------+
|   p   |   p   |   p   |   p   |       |   p   |   p   |   p   |
| -0.88 | -1.42 | -1.31 | -1.14 |       | -1.22 | -1.17 | -0.38 |
+-------+-------+-------+-------+-------+-------+-------+-------+
|       |       |   n   |       |       |       |       |       |
|       |       | -4.16 |       |       |       |       |       |
+-------+-------+-------+-------+-------+-------+-------+-------+
|       |   B   |       |       |   p   |       |       |       |
|       | +4.90 |       |       | -1.45 |       |       |       |
+-------+-------+-------+-------+-------+-------+-------+-------+
|       |       |       |       |   P   |       |       |       |
|       |       |       |       | +2.00 |       |       |       |
+-------+-------+-------+-------+-------+-------+-------+-------+
|       |       |       |       |       |   N   |       |       |
|       |       |       |       |       | +4.21 |       |       |
+-------+-------+-------+-------+-------+-------+-------+-------+
|   P   |   P   |   P   |   P   |       |   P   |   P   |   P   |
| +0.35 | +0.88 | +1.08 | +0.61 |       | +1.15 | +1.56 | +0.51 |
+-------+-------+-------+-------+-------+-------+-------+-------+
|   R   |   N   |   B   |   Q   |   K   |       |       |   R   |
| +4.85 | +4.11 | +4.34 | +10.1 |       |       |       | +5.09 |
+-------+-------+-------+-------+-------+-------+-------+-------+

Final evaluation  +0.31 (white side) [with scaled NNUE, ...]
"""


def test_final_evaluation_is_read_in_centipawns():
    assert parse_eval_trace(SAMPLE).final_cp == 31


def test_squares_map_to_the_right_pieces():
    trace = parse_eval_trace(SAMPLE)
    assert trace.piece_values["b5"].symbol == "B"
    assert trace.piece_values["b5"].value == 4.90
    assert trace.piece_values["c6"].symbol == "n"
    assert trace.piece_values["e5"].symbol == "p"
    assert trace.piece_values["e4"].symbol == "P"
    assert trace.piece_values["a8"].symbol == "r"
    assert trace.piece_values["h1"].symbol == "R"


def test_kings_are_present_but_carry_no_value():
    trace = parse_eval_trace(SAMPLE)
    assert trace.piece_values["e1"].symbol == "K"
    assert trace.piece_values["e1"].value is None
    assert trace.piece_values["e8"].value is None


def test_parsed_placement_matches_the_real_board():
    trace = parse_eval_trace(SAMPLE)
    board = chess.Board()
    for move in ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5"):
        board.push(chess.Move.from_uci(move))
    parsed = {sq: pv.symbol for sq, pv in trace.piece_values.items()}
    actual = {
        chess.square_name(sq): piece.symbol()
        for sq, piece in board.piece_map().items()
    }
    assert parsed == actual


def test_colors_follow_case():
    trace = parse_eval_trace(SAMPLE)
    assert trace.piece_values["b5"].color == chess.WHITE
    assert trace.piece_values["c6"].color == chess.BLACK


def test_magnitude_is_unsigned_so_both_sides_compare():
    trace = parse_eval_trace(SAMPLE)
    assert trace.piece_values["c6"].value == -4.16
    assert trace.piece_values["c6"].magnitude == 4.16


def test_for_color_ranks_by_importance_and_excludes_the_king():
    trace = parse_eval_trace(SAMPLE)
    white = trace.for_color(chess.WHITE)
    assert white[0].square == "d1"  # the queen, at +10.1
    assert all(p.symbol != "K" for p in white)
    assert [p.magnitude for p in white] == sorted(
        (p.magnitude for p in white), reverse=True
    )


def test_in_check_positions_report_no_evaluation():
    trace = parse_eval_trace("Final evaluation: none (in check)")
    assert trace.in_check
    assert trace.final_cp is None
    assert trace.piece_values == {}
