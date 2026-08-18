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
from .values import PIECE_VALUE, join_words, short_piece, with_turn


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


def _captures(board: chess.Board, move: chess.Move) -> Optional[Purpose]:
    if not board.is_capture(move):
        return None
    if board.is_en_passant(move):
        victim = "pawn"
        color = "white" if board.turn == chess.BLACK else "black"
    else:
        piece = board.piece_at(move.to_square)
        if piece is None:
            return None
        victim = chess.piece_name(piece.piece_type)
        color = "white" if piece.color == chess.WHITE else "black"
    return Purpose(
        kind="captures",
        text=f"captures the {color} {victim}",
        ply=0,
        cue=move_cue(move, targets=[move.to_square]),
    )


def _returns_home(board: chess.Board, pv: Sequence[chess.Move]) -> Optional[Purpose]:
    """The same piece can go back to the square it just left."""
    if not pv:
        return None
    first = pv[0]
    after = board.copy(stack=False)
    after.push(first)
    piece = after.piece_at(first.to_square)
    if piece is None:
        return None
    retreat = chess.Move(first.to_square, first.from_square)
    if retreat not in after.legal_moves:
        return None
    san = after.san(retreat)
    return Purpose(
        kind="threatens_return",
        text=f"threatens to play {san}",
        ply=0,
        cue=cue(
            actors=[first.to_square],
            zone=[first.from_square],
            arrows=[
                arrow(first.from_square, first.to_square, "move"),
                arrow(first.to_square, first.from_square, "plan"),
            ],
        ),
    )


def _vacates(board: chess.Board, pv: Sequence[chess.Move]) -> Optional[Purpose]:
    """A later friendly move uses the square this piece left."""
    if not pv:
        return None
    first = pv[0]
    vacated = first.from_square
    name = chess.square_name(vacated)
    later: List[str] = []
    for index, (position, move) in enumerate(_pv_boards(board, pv)):
        if index == 0 or index % 2 != 0:
            continue
        if move.to_square != vacated:
            continue
        later.append(position.san(move))
    if not later:
        return None
    enabled = later[0]
    return Purpose(
        kind="vacates",
        text=f"vacates {name} and enables {enabled}",
        ply=0,
        cue=cue(
            actors=[first.from_square],
            zone=[first.to_square, vacated],
            arrows=[arrow(first.from_square, first.to_square, "move")],
        ),
    )


def _later_intentions(board: chess.Board, pv: Sequence[chess.Move]) -> Optional[Purpose]:
    """Later same-side moves in the line, other than the same piece continuing."""
    sans: List[str] = []
    for index, (position, move) in enumerate(_pv_boards(board, pv)):
        if index == 0 or index % 2 != 0:
            continue
        if move.from_square == pv[0].to_square:
            continue
        san = position.san(move)
        if san not in sans:
            sans.append(san)
        if len(sans) == 2:
            break
    if not sans:
        return None
    if len(sans) == 1:
        text = f"intends to play {sans[0]}"
    else:
        text = f"intends to play {sans[0]} or {sans[1]}"
    return Purpose(kind="intends_later", text=text, ply=0, cue=move_cue(pv[0]))


def _counters(
    board: chess.Board,
    move: chess.Move,
    previous: Optional[chess.Move],
) -> Optional[Purpose]:
    """This move stops a follow-up the opponent's last piece was aiming at."""
    if previous is None:
        return None
    piece = board.piece_at(previous.to_square)
    if piece is None or piece.color == board.turn:
        return None
    threats = [
        candidate
        for candidate in board.legal_moves
        if candidate.from_square == previous.to_square
    ]
    if not threats:
        return None
    after = board.copy(stack=False)
    after.push(move)
    stopped = [threat for threat in threats if threat not in after.legal_moves]
    if not stopped:
        return None
    # Prefer a capture of that piece, else the first follow-up that died.
    named = board.san(stopped[0])
    return Purpose(
        kind="counters",
        text=f"counters the threat of {named}",
        ply=0,
        cue=cue(
            actors=[move.from_square],
            targets=[previous.to_square],
            zone=[move.to_square],
            arrows=[arrow(move.from_square, move.to_square, "move")],
        ),
    )


def _unique(purposes: Sequence[Purpose], *, limit: int) -> List[Purpose]:
    seen: set = set()
    unique: List[Purpose] = []
    for purpose in purposes:
        if purpose.text in seen:
            continue
        seen.add(purpose.text)
        unique.append(purpose)
        if len(unique) >= limit:
            break
    return unique


def explain_move(
    board: chess.Board,
    pv: Sequence[chess.Move],
    *,
    limit: int = 6,
    previous: Optional[chess.Move] = None,
) -> List[Purpose]:
    """Every purpose we can justify for the first move of `pv`.

    Ordered so the concrete, immediate reasons come before the plans that depend
    on the opponent cooperating with the engine's line.
    """
    if not pv:
        return []
    move = pv[0]
    purposes: List[Purpose] = []
    for finder in (_captures, _promotion, _castling, _defends, _rescues):
        found = finder(board, move)
        if found is not None:
            purposes.append(found)
    countered = _counters(board, move, previous)
    if countered is not None:
        purposes.append(countered)
    follow_up = _follow_up(board, pv)
    if follow_up is not None:
        purposes.append(follow_up)
    home = _returns_home(board, pv)
    if home is not None:
        purposes.append(home)
    purposes.extend(_prepared_squares(board, pv))
    vacated = _vacates(board, pv)
    if vacated is not None:
        purposes.append(vacated)
    later = _later_intentions(board, pv)
    if later is not None:
        purposes.append(later)
    return _unique(purposes, limit=limit)


def explain_weaknesses(
    board: chess.Board, pv: Sequence[chess.Move], *, limit: int = 3
) -> List[Purpose]:
    """Opponent replies in the line that this move newly makes legal."""
    if not pv:
        return []
    move = pv[0]
    before_opp = with_turn(board, not board.turn)
    after = board.copy(stack=False)
    after.push(move)
    found: List[Purpose] = []
    for index, (position, reply) in enumerate(_pv_boards(board, pv)):
        if index % 2 == 0:
            continue
        if reply in before_opp.legal_moves:
            continue
        if reply not in after.legal_moves:
            continue
        found.append(
            Purpose(
                kind="enables_opponent",
                text=f"enables {position.san(reply)}",
                ply=index,
                cue=cue(
                    actors=[move.from_square],
                    zone=[move.to_square, reply.to_square],
                    arrows=[
                        arrow(move.from_square, move.to_square, "move"),
                        arrow(reply.from_square, reply.to_square, "threat"),
                    ],
                ),
            )
        )
    return _unique(found, limit=limit)
