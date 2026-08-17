"""Static exchange evaluation — no engine needed, these are pure rules."""

import chess

from decodex.facts import SEE_VALUES, Threat, find_hanging, see


def test_capturing_a_free_pawn_wins_a_pawn():
    board = chess.Board("4k3/8/8/3p4/8/8/8/3RK3 w - - 0 1")
    assert see(board, chess.Move.from_uci("d1d5")) == SEE_VALUES[chess.PAWN]


def test_capturing_a_defended_pawn_with_a_rook_loses_material():
    # The d5 pawn is defended by c6, so Rxd5 concedes the rook.
    board = chess.Board("4k3/8/2p5/3p4/8/8/8/3RK3 w - - 0 1")
    assert see(board, chess.Move.from_uci("d1d5")) < 0


def test_quiet_move_has_no_exchange_value():
    board = chess.Board()
    assert see(board, chess.Move.from_uci("e2e4")) == 0


def test_equal_trade_is_neutral():
    # Rooks trade off on d5 with equal defenders on both sides.
    board = chess.Board("3rk3/8/8/3r4/8/8/8/3RK3 w - - 0 1")
    assert see(board, chess.Move.from_uci("d1d5")) == 0


def test_threat_description_reports_a_material_win():
    threat = Threat(
        mover=chess.WHITE,
        uci="d1d5",
        san="Rxd5",
        cp_white=500,
        mate=None,
        free_tempo=True,
        captures="queen",
        gain_cp=760,
    )
    assert threat.describe() == "White threatens Rxd5, winning the queen"


def test_threat_description_reports_mate():
    threat = Threat(
        mover=chess.BLACK,
        uci="d8d1",
        san="Rd1#",
        cp_white=-100000,
        mate=-1,
        free_tempo=False,
    )
    assert "mate in 1" in threat.describe()


def test_threat_description_stays_quiet_without_a_real_gain():
    # In a lost position the engine's best try is not a threat; saying it
    # "gains -7.60" would be nonsense.
    threat = Threat(
        mover=chess.BLACK,
        uci="e8e7",
        san="Ke7",
        cp_white=510,
        mate=None,
        free_tempo=False,
        gain_cp=-760,
    )
    described = threat.describe()
    assert "gains" not in described
    assert "nothing concrete" in described


def test_threat_description_quotes_a_meaningful_gain():
    threat = Threat(
        mover=chess.WHITE,
        uci="g1f3",
        san="Nf3",
        cp_white=120,
        mate=None,
        free_tempo=True,
        gain_cp=120,
    )
    assert threat.describe() == "White threatens Nf3 (gains 1.20)"


def test_find_hanging_reports_the_loose_queen():
    board = chess.Board("4k3/8/8/3q4/8/8/8/3RK3 w - - 0 1")
    hanging = find_hanging(board)
    assert [(h.square, h.piece_name) for h in hanging] == [("d5", "queen")]
    assert hanging[0].loss_cp == SEE_VALUES[chess.QUEEN]
    assert hanging[0].capture_san == "Rxd5"


def test_find_hanging_ignores_defended_material():
    board = chess.Board("4k3/8/2p5/3p4/8/8/8/3RK3 w - - 0 1")
    assert find_hanging(board) == []


def test_find_hanging_keeps_only_the_best_capture_per_target():
    # Both rooks can take on d5; only one entry should appear for that square.
    board = chess.Board("4k3/8/8/3q4/8/8/8/2RRK3 w - - 0 1")
    hanging = find_hanging(board)
    assert len([h for h in hanging if h.square == "d5"]) == 1
