"""Why the best move is played: the purpose behind it.

DecodeChess renders these as "h4 is beneficial because it intends to play h5"
and "supports advancing the pawn to g5". Both are statements about the principal
variation, not intuitions: the first is the same piece moving again later in the
line, the second is a different unit reaching a square this move defends.

Reading purpose out of the PV is what keeps this honest. If the engine's own
continuation does not contain the follow-up, no claim is made.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import chess

from .cues import EMPTY, Cue, arrow, cue, move_cue
from .values import PIECE_VALUE, join_words, short_piece


@dataclass(frozen=True)
class Purpose:
    """One reason a move is played, traced to the line it came from."""

    kind: str
    text: str
    ply: int
    cue: Cue = field(default=EMPTY)

    def describe(self) -> str:
        return self.text


def _pv_boards(
    board: chess.Board, pv: Sequence[chess.Move]
) -> List[tuple[chess.Board, chess.Move]]:
    """Each position in the line paired with the move played from it."""
    steps: List[tuple[chess.Board, chess.Move]] = []
    walker = board.copy(stack=False)
    for move in pv:
        steps.append((walker.copy(stack=False), move))
        walker.push(move)
    return steps


def _follow_up(
    board: chess.Board, pv: Sequence[chess.Move]
) -> Optional[Purpose]:
    """The same piece moving again later in the line."""
    if not pv:
        return None
    first = pv[0]
    square = first.to_square
    for index, (position, move) in enumerate(_pv_boards(board, pv)):
        if index == 0 or index % 2 != 0:
            continue
        if move.from_square != square:
            continue
        return Purpose(
            kind="follow_up",
            text=f"intends to play {position.san(move)}",
            ply=index,
            # Both hops of the plan: this move, then the same piece going on.
            cue=cue(
                actors=[first.from_square],
                zone=[first.to_square, move.to_square],
                arrows=[
                    arrow(first.from_square, first.to_square, "move"),
                    arrow(move.from_square, move.to_square, "plan"),
                ],
            ),
        )
    return None


def _prepared_squares(
    board: chess.Board, pv: Sequence[chess.Move]
) -> List[Purpose]:
    """Later moves in the line landing on squares this move newly defends.

    The move "supports" such a square: the defence has to exist before the other
    piece can safely go there, which is the causal link DecodeChess reports.
    """
    if not pv:
        return []
    first = pv[0]
    before = board
    after = board.copy(stack=False)
    after.push(first)

    mover = board.turn
    gained = set(after.attacks(first.to_square)) - set(before.attacks(first.from_square))
    purposes: List[Purpose] = []
    for index, (position, move) in enumerate(_pv_boards(board, pv)):
        if index == 0 or index % 2 != 0:
            continue
        if move.to_square not in gained:
            continue
        if move.from_square == first.to_square:
            continue
        piece = position.piece_at(move.from_square)
        if piece is None or piece.color != mover:
            continue
        target = chess.square_name(move.to_square)
        if piece.piece_type == chess.PAWN:
            text = f"supports advancing the pawn to {target}"
        else:
            text = (
                f"supports bringing the {chess.piece_name(piece.piece_type)} "
                f"to {target}"
            )
        purposes.append(
            Purpose(
                kind="prepares",
                text=text,
                ply=index,
                cue=cue(
                    actors=[first.from_square],
                    zone=[first.to_square],
                    friends=[move.to_square],
                    arrows=[
                        arrow(first.from_square, first.to_square, "move"),
                        arrow(move.from_square, move.to_square, "plan"),
                        # The defence that makes the square available is the
                        # causal link being claimed, so draw it too.
                        arrow(first.to_square, move.to_square, "support"),
                    ],
                ),
            )
        )
    return purposes


def _rescues(board: chess.Board, move: chess.Move) -> Optional[Purpose]:
    """The move steps a piece off a square where it was attacked and undefended."""
    piece = board.piece_at(move.from_square)
    if piece is None or piece.piece_type == chess.KING:
        return None
    if PIECE_VALUE[piece.piece_type] < PIECE_VALUE[chess.KNIGHT]:
        return None
    attackers = board.attackers(not piece.color, move.from_square)
    if not attackers:
        return None
    cheapest = min(PIECE_VALUE[board.piece_type_at(s) or chess.PAWN] for s in attackers)
    if cheapest >= PIECE_VALUE[piece.piece_type]:
        return None
    after = board.copy(stack=False)
    after.push(move)
    if after.attackers(not piece.color, move.to_square) and not after.attackers(
        piece.color, move.to_square
    ):
        return None
    return Purpose(
        kind="rescues",
        text=(
            f"moves the {chess.piece_name(piece.piece_type)} off "
            f"{chess.square_name(move.from_square)}, where it was attacked"
        ),
        ply=0,
        cue=cue(
            actors=[move.from_square],
            zone=[move.to_square],
            targets=attackers,
            arrows=[arrow(move.from_square, move.to_square, "move")]
            + [arrow(square, move.from_square, "threat") for square in attackers],
        ),
    )


def _defends(board: chess.Board, move: chess.Move) -> Optional[Purpose]:
    """The move newly defends a friendly piece that was attacked and loose."""
    mover = board.turn
    after = board.copy(stack=False)
    after.push(move)
    gained = set(after.attacks(move.to_square)) - set(board.attacks(move.from_square))
    rescued: List[str] = []
    saved: List[chess.Square] = []
    for square in sorted(gained):
        piece = board.piece_at(square)
        if piece is None or piece.color != mover:
            continue
        if piece.piece_type == chess.KING:
            continue
        if PIECE_VALUE[piece.piece_type] < PIECE_VALUE[chess.KNIGHT]:
            continue
        if not board.attackers(not mover, square):
            continue
        if board.attackers(mover, square):
            continue
        rescued.append(short_piece(board, square))
        saved.append(square)
    if not rescued:
        return None
    return Purpose(
        kind="defends",
        text=f"defends {join_words(rescued)}",
        ply=0,
        cue=cue(
            actors=[move.from_square],
            zone=[move.to_square],
            friends=saved,
            arrows=[arrow(move.from_square, move.to_square, "move")]
            + [arrow(move.to_square, square, "support") for square in saved],
        ),
    )


def _castling(board: chess.Board, move: chess.Move) -> Optional[Purpose]:
    if not board.is_castling(move):
        return None
    side = "short" if chess.square_file(move.to_square) > 4 else "long"
    return Purpose(
        kind="castling",
        text=f"castles {side}, tucking the king away",
        ply=0,
        cue=move_cue(move),
    )


def _promotion(board: chess.Board, move: chess.Move) -> Optional[Purpose]:
    if move.promotion is None:
        return None
    return Purpose(
        kind="promotion",
        text=f"promotes to a {chess.piece_name(move.promotion)}",
        ply=0,
        cue=move_cue(move),
    )


def explain_move(
    board: chess.Board, pv: Sequence[chess.Move], *, limit: int = 4
) -> List[Purpose]:
    """Every purpose we can justify for the first move of `pv`.

    Ordered so the concrete, immediate reasons come before the plans that depend
    on the opponent cooperating with the engine's line.
    """
    if not pv:
        return []
    move = pv[0]
    purposes: List[Purpose] = []
    for finder in (_promotion, _castling, _defends, _rescues):
        found = finder(board, move)
        if found is not None:
            purposes.append(found)
    follow_up = _follow_up(board, pv)
    if follow_up is not None:
        purposes.append(follow_up)
    purposes.extend(_prepared_squares(board, pv))

    seen: set = set()
    unique: List[Purpose] = []
    for purpose in purposes:
        if purpose.text in seen:
            continue
        seen.add(purpose.text)
        unique.append(purpose)
    return unique[:limit]
