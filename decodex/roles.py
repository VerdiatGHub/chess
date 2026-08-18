"""What each piece is doing.

DecodeChess calls this Piece Roles. A role is a checkable statement about a
piece's function in the position: what it guards, what it blocks, whether it is
stuck. Each detector below is a predicate over the board, so a role is either
demonstrably true or it is not claimed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import chess

from .cues import Cue, arrow, cue
from .values import PIECE_VALUE, color_word, join_words, short_piece, with_turn


@dataclass(frozen=True)
class Role:
    """One piece and everything it is doing, in priority order."""

    square: chess.Square
    piece_type: chess.PieceType
    color: chess.Color
    labels: List[str] = field(default_factory=list)
    value_cp: int = 0
    guarding: Tuple[chess.Square, ...] = ()
    attacking: Tuple[chess.Square, ...] = ()
    shelters: Optional[chess.Square] = None

    @property
    def name(self) -> str:
        return chess.piece_name(self.piece_type)

    def describe(self) -> str:
        where = chess.square_name(self.square)
        return (
            f"the {color_word(self.color)} {self.name} on {where} "
            f"{join_clauses(self.labels)}"
        )

    def cue(self) -> Cue:
        """The piece, what it guards, what it attacks, and the king it shields.

        Duties without a second square — pinned, on an outpost, out of moves —
        still light the piece itself, which is the whole claim in those cases.
        """
        friends = list(self.guarding)
        if self.shelters is not None:
            friends.append(self.shelters)
        return cue(
            actors=[self.square],
            friends=friends,
            targets=list(self.attacking),
            arrows=[arrow(self.square, target, "support") for target in self.guarding]
            + [arrow(self.square, target, "attack") for target in self.attacking],
        )


def join_clauses(labels: Sequence[str]) -> str:
    if len(labels) <= 1:
        return "".join(labels)
    return ", ".join(labels[:-1]) + f", and {labels[-1]}"


def _guards(board: chess.Board, square: chess.Square, color: chess.Color) -> List[chess.Square]:
    """Friendly pieces of real value that this piece defends, and that need it."""
    guarded = []
    for target in board.attacks(square):
        piece = board.piece_at(target)
        if piece is None or piece.color != color:
            continue
        if piece.piece_type == chess.KING:
            continue
        if PIECE_VALUE[piece.piece_type] < PIECE_VALUE[chess.KNIGHT]:
            continue
        if not board.attackers(not color, target):
            continue
        guarded.append(target)
    return guarded


def _is_only_defender(
    board: chess.Board, square: chess.Square, target: chess.Square, color: chess.Color
) -> bool:
    defenders = [s for s in board.attackers(color, target) if s != target]
    return defenders == [square]


def _king_shelter(board: chess.Board, color: chess.Color) -> List[chess.Square]:
    """Pawns immediately in front of the king, which is what shields it."""
    king = board.king(color)
    if king is None:
        return []
    forward = 1 if color == chess.WHITE else -1
    shelter = []
    king_file = chess.square_file(king)
    king_rank = chess.square_rank(king)
    for file_offset in (-1, 0, 1):
        file_index = king_file + file_offset
        if not 0 <= file_index <= 7:
            continue
        for rank_offset in (1, 2):
            rank_index = king_rank + forward * rank_offset
            if not 0 <= rank_index <= 7:
                continue
            square = chess.square(file_index, rank_index)
            piece = board.piece_at(square)
            if piece is not None and piece.color == color and piece.piece_type == chess.PAWN:
                shelter.append(square)
    return shelter


def _is_outpost(board: chess.Board, square: chess.Square, color: chess.Color) -> bool:
    """A knight or bishop on enemy ground that no enemy pawn can evict."""
    piece = board.piece_at(square)
    if piece is None or piece.piece_type not in (chess.KNIGHT, chess.BISHOP):
        return False
    rank = chess.square_rank(square)
    advanced = rank >= 4 if color == chess.WHITE else rank <= 3
    if not advanced:
        return False
    if not board.attackers(color, square):
        return False
    file_index = chess.square_file(square)
    forward = 1 if color == chess.WHITE else -1
    for offset in (-1, 1):
        neighbour = file_index + offset
        if not 0 <= neighbour <= 7:
            continue
        rank_index = rank
        while 0 <= rank_index + forward <= 7:
            rank_index += forward
            candidate = board.piece_at(chess.square(neighbour, rank_index))
            if (
                candidate is not None
                and candidate.color != color
                and candidate.piece_type == chess.PAWN
            ):
                return False
    return True


def _mobility(board: chess.Board, square: chess.Square) -> int:
    """Legal moves for the piece on `square`.

    The caller must pass a board on which that piece's side is to move, or every
    piece looks frozen.
    """
    return sum(1 for move in board.legal_moves if move.from_square == square)


def _open_file(board: chess.Board, square: chess.Square, color: chess.Color) -> Optional[str]:
    file_index = chess.square_file(square)
    own = enemy = 0
    for rank in range(8):
        piece = board.piece_at(chess.square(file_index, rank))
        if piece is None or piece.piece_type != chess.PAWN:
            continue
        if piece.color == color:
            own += 1
        else:
            enemy += 1
    if own == 0 and enemy == 0:
        return "an open file"
    if own == 0:
        return "a half-open file"
    return None


def _is_under_fire(board: chess.Board, square: chess.Square, color: chess.Color) -> bool:
    return bool(board.attackers(not color, square))


def _is_undeveloped(board: chess.Board, square: chess.Square, color: chess.Color) -> bool:
    """Whether this piece is still sitting on its own starting square.

    Such a piece may well have no moves, but that makes it undeveloped rather
    than trapped, and calling it trapped in the opening is misleading.
    """
    rank = 0 if color == chess.WHITE else 7
    if chess.square_rank(square) != rank:
        return False
    starts = {
        0: chess.ROOK,
        1: chess.KNIGHT,
        2: chess.BISHOP,
        3: chess.QUEEN,
        5: chess.BISHOP,
        6: chess.KNIGHT,
        7: chess.ROOK,
    }
    expected = starts.get(chess.square_file(square))
    piece = board.piece_at(square)
    return piece is not None and piece.piece_type == expected


def describe_roles(
    board: chess.Board, color: chess.Color, *, limit: int = 6
) -> List[Role]:
    """The roles worth reporting for one side, most engaged piece first.

    A duty is only a duty when something is at stake, so defences are reported
    only when the defended piece is under attack. Without that filter every
    opening position reads as a list of pieces guarding each other, which is true
    and useless.
    """
    roles: List[Role] = []
    shelter = set(_king_shelter(board, color))
    king = board.king(color)
    # Mobility and pin questions are only meaningful when this side is to move.
    movable = with_turn(board, color)
    for square, piece in board.piece_map().items():
        if piece.color != color:
            continue
        labels: List[str] = []

        guarded = _guards(board, square, color)
        sole = [
            target
            for target in board.attacks(square)
            if (occupant := board.piece_at(target)) is not None
            and occupant.color == color
            and occupant.piece_type != chess.KING
            and PIECE_VALUE[occupant.piece_type] >= PIECE_VALUE[chess.KNIGHT]
            and _is_under_fire(board, target, color)
            and _is_only_defender(board, square, target, color)
        ]
        if sole:
            labels.append(
                f"is the only defender of "
                f"{join_words([short_piece(board, t) for t in sole])}"
            )
        elif guarded:
            labels.append(
                f"defends {join_words([short_piece(board, t) for t in guarded])}"
            )
        guarding = sole or guarded

        attacked = [
            target
            for target in board.attacks(square)
            if (occupant := board.piece_at(target)) is not None
            and occupant.color != color
            and PIECE_VALUE[occupant.piece_type] >= PIECE_VALUE[chess.KNIGHT]
        ]
        if attacked:
            labels.append(
                f"attacks {join_words([short_piece(board, t) for t in attacked])}"
            )

        shields_king = False
        if piece.piece_type == chess.PAWN:
            if square in shelter:
                labels.append("shields the king")
                shields_king = True
            if not labels:
                continue
        else:
            if movable.is_pinned(color, square):
                labels.append("is pinned and cannot move freely")
            if _is_outpost(board, square, color):
                labels.append("sits on an outpost no pawn can challenge")
            if piece.piece_type in (chess.ROOK, chess.QUEEN):
                file_state = _open_file(board, square, color)
                if file_state:
                    labels.append(f"stands on {file_state}")
            # A piece on its starting square with no moves is undeveloped, not
            # trapped, and saying "trapped" in the opening misleads.
            if (
                piece.piece_type != chess.KING
                and not _is_undeveloped(board, square, color)
                and _mobility(movable, square) == 0
            ):
                labels.append("has no moves at all")

        if not labels:
            continue
        roles.append(
            Role(
                square=square,
                piece_type=piece.piece_type,
                color=color,
                labels=labels,
                value_cp=PIECE_VALUE[piece.piece_type],
                guarding=tuple(guarding),
                attacking=tuple(attacked),
                shelters=king if shields_king else None,
            )
        )

    roles.sort(key=lambda role: (len(role.labels), role.value_cp), reverse=True)
    return roles[:limit]
