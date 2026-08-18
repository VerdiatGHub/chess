"""Tactical geometry.

Written from first principles rather than adapted from lichess-puzzler, whose
detectors are AGPL-3.0. Every function here answers a question about the board
that can be checked by inspection: which pieces stand on a line, what a move
newly attacks, what defends what. Nothing is inferred.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import chess

from .cues import Cue, Insight, arrow, between, cue
from .values import (
    PIECE_VALUE,
    color_word,
    describe_piece,
    join_words,
    short_piece,
)

# File and rank steps for the two sliding families.
_DIAGONAL = ((1, 1), (1, -1), (-1, 1), (-1, -1))
_STRAIGHT = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _directions(piece_type: chess.PieceType) -> Tuple[Tuple[int, int], ...]:
    if piece_type == chess.BISHOP:
        return _DIAGONAL
    if piece_type == chess.ROOK:
        return _STRAIGHT
    if piece_type == chess.QUEEN:
        return _DIAGONAL + _STRAIGHT
    return ()


def _walk(square: chess.Square, step: Tuple[int, int]) -> Iterable[chess.Square]:
    """Squares outward from `square` in one direction, stopping at the edge."""
    file_index = chess.square_file(square)
    rank_index = chess.square_rank(square)
    while True:
        file_index += step[0]
        rank_index += step[1]
        if not (0 <= file_index <= 7 and 0 <= rank_index <= 7):
            return
        yield chess.square(file_index, rank_index)


def _first_two_occupied(
    board: chess.Board, square: chess.Square, step: Tuple[int, int]
) -> Tuple[Optional[chess.Square], Optional[chess.Square]]:
    """The nearest two occupied squares along a ray, nearest first."""
    found: List[chess.Square] = []
    for candidate in _walk(square, step):
        if board.piece_at(candidate) is not None:
            found.append(candidate)
            if len(found) == 2:
                break
    while len(found) < 2:
        found.append(None)  # type: ignore[arg-type]
    return found[0], found[1]


@dataclass(frozen=True)
class Alignment:
    """Two enemy pieces on one line behind a single attacker.

    A pin when the near piece is the cheaper of the two (or the far piece is the
    king), a skewer when the near piece is dearer. `absolute` marks a pin against
    the king, which cannot legally be broken by moving the pinned piece.
    """

    kind: str
    attacker: chess.Square
    near: chess.Square
    far: chess.Square
    by: chess.Color
    absolute: bool = False

    def describe(self, board: chess.Board) -> str:
        near = short_piece(board, self.near)
        far = short_piece(board, self.far)
        attacker = short_piece(board, self.attacker)
        if self.kind == "pin":
            qualifier = "absolutely " if self.absolute else ""
            return (
                f"the {color_word(not self.by)} {near} is {qualifier}pinned "
                f"to the {far} by the {color_word(self.by)} {attacker}"
            )
        return (
            f"the {color_word(not self.by)} {near} is skewered, with the {far} "
            f"behind it, by the {color_word(self.by)} {attacker}"
        )

    def cue(self) -> Cue:
        """The attacker, both victims, and the line the three stand on."""
        return cue(
            actors=[self.attacker],
            targets=[self.near, self.far],
            zone=between(self.attacker, self.far),
            arrows=[arrow(self.attacker, self.far, "attack")],
        )

    def insight(self, board: chess.Board) -> Insight:
        return Insight(self.describe(board), self.cue())


def find_alignments(board: chess.Board, by: Optional[chess.Color] = None) -> List[Alignment]:
    """Pins and skewers currently on the board.

    Both pieces on the line must be worth talking about. A bishop with a pawn
    behind it is geometrically a skewer, but reporting it would bury the real
    ones, so the rear piece must be at least a knight unless it is the king.
    """
    found: List[Alignment] = []
    colors = (chess.WHITE, chess.BLACK) if by is None else (by,)
    for color in colors:
        for piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            for attacker in board.pieces(piece_type, color):
                for step in _directions(piece_type):
                    near, far = _first_two_occupied(board, attacker, step)
                    if near is None or far is None:
                        continue
                    near_piece = board.piece_at(near)
                    far_piece = board.piece_at(far)
                    if near_piece is None or far_piece is None:
                        continue
                    if near_piece.color == color or far_piece.color == color:
                        continue
                    if near_piece.piece_type == chess.KING:
                        continue
                    absolute = far_piece.piece_type == chess.KING
                    near_value = PIECE_VALUE[near_piece.piece_type]
                    far_value = PIECE_VALUE[far_piece.piece_type]
                    if not absolute and far_value < PIECE_VALUE[chess.KNIGHT]:
                        continue
                    if absolute or far_value > near_value:
                        kind = "pin"
                    elif near_value > far_value:
                        kind = "skewer"
                    else:
                        continue
                    found.append(
                        Alignment(
                            kind=kind,
                            attacker=attacker,
                            near=near,
                            far=far,
                            by=color,
                            absolute=absolute,
                        )
                    )
    return found


@dataclass(frozen=True)
class Battery:
    """Two friendly sliders stacked on one line, the rear supporting the front."""

    front: chess.Square
    rear: chess.Square
    color: chess.Color
    target: Optional[chess.Square] = None

    def describe(self, board: chess.Board) -> str:
        text = (
            f"the {color_word(self.color)} {short_piece(board, self.rear)} "
            f"stands behind the {short_piece(board, self.front)}"
        )
        if self.target is not None:
            text += f", aimed at {describe_piece(board, self.target)}"
        return text

    def cue(self) -> Cue:
        """Both sliders, plus the arrow along the line they share."""
        far = self.target if self.target is not None else self.front
        return cue(
            actors=[self.rear, self.front],
            targets=[self.target] if self.target is not None else [],
            zone=between(self.rear, far),
            arrows=[arrow(self.rear, far, "support" if self.target is None else "attack")],
        )

    def insight(self, board: chess.Board) -> Insight:
        return Insight(self.describe(board), self.cue())


def find_batteries(board: chess.Board, color: Optional[chess.Color] = None) -> List[Battery]:
    """Stacked sliders, one pair per line.

    Each pair is found twice, once from either end, so pairs are collapsed and
    the version aimed at something is kept in preference to the bare stack.
    """
    best: Dict[frozenset, Battery] = {}
    colors = (chess.WHITE, chess.BLACK) if color is None else (color,)
    for side in colors:
        for piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            for rear in board.pieces(piece_type, side):
                for step in _directions(piece_type):
                    front, beyond = _first_two_occupied(board, rear, step)
                    if front is None:
                        continue
                    front_piece = board.piece_at(front)
                    if front_piece is None or front_piece.color != side:
                        continue
                    # The front piece must travel the same line for the pair to
                    # act as one unit.
                    if step not in _directions(front_piece.piece_type):
                        continue
                    target = None
                    if beyond is not None:
                        beyond_piece = board.piece_at(beyond)
                        if beyond_piece is not None and beyond_piece.color != side:
                            target = beyond
                    battery = Battery(front=front, rear=rear, color=side, target=target)
                    key = frozenset((front, rear))
                    existing = best.get(key)
                    if existing is None or (
                        existing.target is None and target is not None
                    ):
                        best[key] = battery
    return list(best.values())


@dataclass(frozen=True)
class Relation:
    """One piece bearing on another: "can capture", or "supports"."""

    kind: str
    subject: chess.Square
    object: chess.Square

    def describe(self, board: chess.Board) -> str:
        verb = "can capture" if self.kind == "attack" else "supports"
        return (
            f"{describe_piece(board, self.subject)} {verb} "
            f"{describe_piece(board, self.object)}"
        )

    def cue(self) -> Cue:
        return cue(
            actors=[self.subject],
            targets=[self.object] if self.kind == "attack" else [],
            friends=[self.object] if self.kind == "support" else [],
            arrows=[arrow(self.subject, self.object, self.kind)],
        )

    def insight(self, board: chess.Board) -> Insight:
        return Insight(self.describe(board), self.cue())


def _defenders(board: chess.Board, square: chess.Square) -> List[chess.Square]:
    piece = board.piece_at(square)
    if piece is None:
        return []
    return [s for s in board.attackers(piece.color, square) if s != square]


def notable_relations(
    board: chess.Board, *, perspective: Optional[chess.Color] = None, limit: int = 6
) -> List[Relation]:
    """The attack and support relations worth pointing out.

    Restricted to targets of real value, and ranked with attacks ahead of
    defences: what can be captured is more urgent than what is merely guarded,
    and a full board has far too many relations to list them all.
    """
    scored: List[Tuple[int, int, Relation]] = []
    for square, piece in board.piece_map().items():
        if piece.piece_type == chess.KING:
            continue
        if perspective is not None and piece.color != perspective:
            continue
        value = PIECE_VALUE[piece.piece_type]
        if value < PIECE_VALUE[chess.KNIGHT]:
            continue
        for attacker in board.attackers(not piece.color, square):
            scored.append((1, value, Relation("attack", attacker, square)))
        # Only mention a defence of something that is actually under fire.
        if not board.attackers(not piece.color, square):
            continue
        for defender in _defenders(board, square):
            scored.append((0, value, Relation("support", defender, square)))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    seen: set = set()
    unique: List[Relation] = []
    for _, _, relation in scored:
        key = (relation.kind, relation.subject, relation.object)
        if key in seen:
            continue
        seen.add(key)
        unique.append(relation)
        if len(unique) >= limit:
            break
    return unique


def relation_insights(
    board: chess.Board, *, perspective: Optional[chess.Color] = None, limit: int = 6
) -> List[Insight]:
    """The "Pay attention to" list: contact between pieces, with its geometry."""
    return [
        relation.insight(board)
        for relation in notable_relations(board, perspective=perspective, limit=limit)
    ]


@dataclass(frozen=True)
class Fork:
    """One move putting two or more valuable enemy pieces under attack.

    Target names are resolved when the fork is found, because they describe the
    position *after* the move, which the reporting layer does not hold. The
    squares are kept alongside for the same reason.
    """

    uci: str
    san: str
    targets: Tuple[str, ...]
    value_cp: int
    gives_check: bool
    origin: chess.Square
    landing: chess.Square
    target_squares: Tuple[chess.Square, ...] = ()

    def describe(self) -> str:
        prefix = "checks and forks" if self.gives_check else "forks"
        return f"{self.san} {prefix} {join_words(self.targets)}"

    def cue(self) -> Cue:
        """The move itself, then a fan of arrows from the square it lands on."""
        return cue(
            actors=[self.origin],
            zone=[self.landing],
            targets=self.target_squares,
            arrows=[arrow(self.origin, self.landing, "move")]
            + [arrow(self.landing, target, "attack") for target in self.target_squares],
        )

    def insight(self) -> Insight:
        return Insight(self.describe(), self.cue())


def _is_worth_forking(
    board: chess.Board, mover_value: int, target: chess.Square
) -> bool:
    """A target counts if taking it wins material, or if it is undefended."""
    piece = board.piece_at(target)
    if piece is None:
        return False
    if piece.piece_type == chess.KING:
        return True
    if PIECE_VALUE[piece.piece_type] > mover_value:
        return True
    return not _defenders(board, target)


def find_forks(board: chess.Board, *, limit: int = 4) -> List[Fork]:
    """Forks available to the side to move."""
    found: List[Fork] = []
    for move in board.legal_moves:
        piece = board.piece_at(move.from_square)
        if piece is None:
            continue
        after = board.copy(stack=False)
        after.push(move)
        landed = after.piece_at(move.to_square)
        if landed is None:
            continue
        mover_value = PIECE_VALUE[landed.piece_type]
        targets = [
            square
            for square in after.attacks(move.to_square)
            if (occupant := after.piece_at(square)) is not None
            and occupant.color != piece.color
            and _is_worth_forking(after, mover_value, square)
        ]
        if len(targets) < 2:
            continue
        # The king cannot be taken, so it adds no material to the tally.
        value = sum(
            PIECE_VALUE[after.piece_type_at(square) or chess.PAWN]
            for square in targets
            if after.piece_type_at(square) != chess.KING
        )
        found.append(
            Fork(
                uci=move.uci(),
                san=board.san(move),
                targets=tuple(short_piece(after, square) for square in targets),
                value_cp=value,
                gives_check=after.is_check(),
                origin=move.from_square,
                landing=move.to_square,
                target_squares=tuple(targets),
            )
        )
    found.sort(key=lambda fork: (fork.gives_check, fork.value_cp), reverse=True)
    return found[:limit]


@dataclass(frozen=True)
class DiscoveredAttack:
    """A move stepping off a line, unveiling a friendly slider behind it."""

    uci: str
    san: str
    unveiled: str
    target: str
    origin: chess.Square
    landing: chess.Square
    slider: chess.Square
    target_square: chess.Square

    def describe(self) -> str:
        return f"{self.san} uncovers the {self.unveiled}, hitting the {self.target}"

    def cue(self) -> Cue:
        """The piece that steps aside, and the line it opens behind itself."""
        return cue(
            actors=[self.origin, self.slider],
            zone=[self.landing] + between(self.slider, self.target_square),
            targets=[self.target_square],
            arrows=[
                arrow(self.origin, self.landing, "move"),
                arrow(self.slider, self.target_square, "attack"),
            ],
        )

    def insight(self) -> Insight:
        return Insight(self.describe(), self.cue())


def find_discovered_attacks(board: chess.Board, *, limit: int = 3) -> List[DiscoveredAttack]:
    """Discovered attacks available to the side to move.

    A slider that was not hitting a square before the move, and is hitting an
    undefended enemy piece after it, has been uncovered by the move.
    """
    mover = board.turn
    sliders = {
        square: set(board.attacks(square))
        for square, piece in board.piece_map().items()
        if piece.color == mover
        and piece.piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN)
    }
    found: List[DiscoveredAttack] = []
    seen: set = set()
    for move in board.legal_moves:
        if move.uci() in seen:
            continue
        after = board.copy(stack=False)
        after.push(move)
        for slider, was_attacking in sliders.items():
            if slider == move.from_square:
                continue
            piece = after.piece_at(slider)
            if piece is None or piece.color != mover:
                continue
            for square in sorted(set(after.attacks(slider)) - was_attacking):
                occupant = after.piece_at(square)
                if occupant is None or occupant.color == mover:
                    continue
                if PIECE_VALUE[occupant.piece_type] < PIECE_VALUE[chess.KNIGHT]:
                    continue
                if _defenders(after, square):
                    continue
                seen.add(move.uci())
                found.append(
                    DiscoveredAttack(
                        uci=move.uci(),
                        san=board.san(move),
                        unveiled=short_piece(after, slider),
                        target=short_piece(after, square),
                        origin=move.from_square,
                        landing=move.to_square,
                        slider=slider,
                        target_square=square,
                    )
                )
                break
            if move.uci() in seen:
                break
    return found[:limit]


def tactic_insights(board: chess.Board, *, limit: int = 6) -> List[Insight]:
    """Every motif on the board or one move away, for the side to move.

    Standing geometry comes first: a pin that already exists is more use to a
    reader than a fork that depends on finding one specific move. Batteries with
    no target are dropped, since two rooks stacked on a closed file are a fact
    without being a feature.
    """
    found: List[Insight] = []
    found.extend(item.insight(board) for item in find_alignments(board))
    found.extend(
        item.insight(board)
        for item in find_batteries(board)
        if item.target is not None
    )
    found.extend(item.insight() for item in find_forks(board))
    found.extend(item.insight() for item in find_discovered_attacks(board))
    return found[:limit]
