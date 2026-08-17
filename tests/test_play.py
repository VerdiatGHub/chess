"""The play-vs-bot session. Bot moves need an engine; the rest is pure rules."""

import chess
import chess.pgn
import io
import pytest

from decodex.play import PlaySession


def test_human_is_the_other_color():
    assert PlaySession(bot_color=chess.BLACK).human_color == chess.WHITE
    assert PlaySession(bot_color=chess.WHITE).human_color == chess.BLACK


def test_bot_turn_tracks_the_board():
    session = PlaySession(bot_color=chess.BLACK)
    assert not session.bot_to_move
    session.push_san_or_uci("e4")
    assert session.bot_to_move


def test_moves_accepted_as_san_and_uci():
    session = PlaySession(bot_color=chess.BLACK)
    assert session.push_san_or_uci("e4").uci() == "e2e4"
    assert session.push_san_or_uci("e7e5").uci() == "e7e5"
    assert len(session.moves) == 2


def test_illegal_move_is_rejected_and_changes_nothing():
    session = PlaySession(bot_color=chess.BLACK)
    with pytest.raises(ValueError):
        session.push_san_or_uci("e5")
    assert session.moves == []
    assert session.board.fen() == chess.STARTING_FEN


def test_undo_rewinds_both_sides():
    session = PlaySession(bot_color=chess.BLACK)
    session.push_san_or_uci("e4")
    session.push_san_or_uci("e5")
    session.undo(2)
    assert session.moves == []
    assert session.board.fen() == chess.STARTING_FEN


def test_undo_past_the_start_is_harmless():
    session = PlaySession(bot_color=chess.BLACK)
    session.undo(5)
    assert session.board.fen() == chess.STARTING_FEN


def test_status_reports_check_and_mate():
    session = PlaySession(bot_color=chess.BLACK)
    for san in ("e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6"):
        session.push_san_or_uci(san)
    session.push_san_or_uci("Qxf7#")
    assert "Checkmate" in session.status()
    assert "White wins" in session.status()


def test_pgn_round_trips_through_a_parser():
    session = PlaySession(bot_color=chess.BLACK)
    for san in ("e4", "e5", "Nf3"):
        session.push_san_or_uci(san)
    pgn = session.to_pgn({"Event": "test"})

    game = chess.pgn.read_game(io.StringIO(pgn))
    assert game is not None
    assert game.headers["Event"] == "test"
    assert game.headers["Black"] == "Bot"
    assert [m.uci() for m in game.mainline_moves()] == ["e2e4", "e7e5", "g1f3"]


def test_unfinished_game_has_an_open_result():
    session = PlaySession(bot_color=chess.BLACK)
    session.push_san_or_uci("e4")
    assert 'Result "*"' in session.to_pgn()


@pytest.mark.engine
def test_bot_replies_with_a_legal_move(search_engine):
    session = PlaySession(bot_color=chess.BLACK, skill=1, move_time=0.05)
    session.push_san_or_uci("e4")
    before = session.board.copy()
    move = session.bot_move(search_engine)
    assert move is not None
    assert move in before.legal_moves
    assert session.board.turn == chess.WHITE


@pytest.mark.engine
def test_bot_declines_to_move_out_of_turn(search_engine):
    session = PlaySession(bot_color=chess.BLACK, skill=1, move_time=0.05)
    assert session.bot_move(search_engine) is None
    assert session.moves == []
