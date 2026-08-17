"""Shared constants and naming helpers.

This is the leaf module of the package: it imports nothing of ours, so the
static layers and the search layers can both depend on it without cycles.
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence

import chess

PIECE_VALUE: Dict[chess.PieceType, int] = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 20000,
}

MATE_SCORE = 100_000

_NAMES = {
    "p": "pawn",
    "n": "knight",
    "b": "bishop",
    "r": "rook",
    "q": "queen",
    "k": "king",
}


def piece_name(symbol: str) -> str:
    return _NAMES[symbol.lower()]


def color_word(color: chess.Color) -> str:
    return "white" if color == chess.WHITE else "black"


def side_word(color: Optional[chess.Color]) -> str:
    if color is None:
        return "Both sides"
    return "White" if color == chess.WHITE else "Black"


def describe_piece(board: chess.Board, square: chess.Square) -> str:
    """Render as "the white bishop on b3", matching the prose sections."""
    piece = board.piece_at(square)
    if piece is None:
        return f"the empty square {chess.square_name(square)}"
    return (
        f"the {color_word(piece.color)} {chess.piece_name(piece.piece_type)} "
        f"on {chess.square_name(square)}"
    )


def short_piece(board: chess.Board, square: chess.Square) -> str:
    """Render as "bishop on b3", where the colour is already established."""
    piece = board.piece_at(square)
    if piece is None:
        return chess.square_name(square)
    return f"{chess.piece_name(piece.piece_type)} on {chess.square_name(square)}"


def join_words(items: Sequence[str]) -> str:
    """Join with "the" on each item, so lists read as English."""
    labelled = [f"the {item}" for item in items]
    if len(labelled) <= 1:
        return "".join(labelled)
    return ", ".join(labelled[:-1]) + f" and {labelled[-1]}"


def with_turn(board: chess.Board, color: chess.Color) -> chess.Board:
    """The same position with `color` to move.

    Rebuilt from FEN rather than by pushing a null move, because python-chess
    warns when it has to send a history containing null moves to the engine. En
    passant rights are dropped, which is correct: a skipped move forfeits them.
    """
    if board.turn == color:
        return board
    fields = board.fen().split()
    fields[1] = "w" if color == chess.WHITE else "b"
    fields[3] = "-"
    return chess.Board(" ".join(fields))
