"""Board geometry attached to a fact, so a statement can be shown as well as read.

DecodeChess draws arrows and lights up squares as you hover an idea. That is only
honest if the geometry comes from the same detector that produced the sentence:
a drawn arrow is another claim about the position, and inferring one from the
prose would reintroduce exactly the guessing the rest of this package avoids.

So every detector that can name a square hands its squares over here, next to the
words it already wrote. If a detector cannot justify a square, its cue is empty
and the UI draws nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Sequence, Tuple, Union

import chess

SquareLike = Union[chess.Square, str]

# Why a square is lit. The vocabulary is deliberately tiny: a reader learns four
# colours, not twenty.
MARK_TONES = ("actor", "target", "friend", "zone")

# Why an arrow is drawn. "move" is a move that could be played, "plan" a later
# move in the same line, "threat" what the opponent is aiming at.
ARROW_TONES = ("move", "plan", "attack", "support", "threat")


def square_name(square: SquareLike) -> str:
    """Accept either a python-chess square index or a name, return the name."""
    if isinstance(square, str):
        if square not in chess.SQUARE_NAMES:
            raise ValueError(f"not a square: {square!r}")
        return square
    return chess.square_name(square)


@dataclass(frozen=True)
class Mark:
    """One square worth lighting up, and what it is doing in the statement."""

    square: str
    tone: str

    def __post_init__(self) -> None:
        if self.tone not in MARK_TONES:
            raise ValueError(f"unknown mark tone: {self.tone!r}")


@dataclass(frozen=True)
class Arrow:
    """One relation between two squares, drawn from origin to target."""

    origin: str
    target: str
    tone: str

    def __post_init__(self) -> None:
        if self.tone not in ARROW_TONES:
            raise ValueError(f"unknown arrow tone: {self.tone!r}")
        if self.origin == self.target:
            raise ValueError("an arrow needs two different squares")


@dataclass(frozen=True)
class Cue:
    """Everything to draw for one fact."""

    marks: Tuple[Mark, ...] = ()
    arrows: Tuple[Arrow, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.marks or self.arrows)

    def merge(self, other: "Cue") -> "Cue":
        return cue(marks=self.marks + other.marks, arrows=self.arrows + other.arrows)


EMPTY = Cue()


def _dedupe_marks(marks: Iterable[Mark]) -> Tuple[Mark, ...]:
    """One mark per square, keeping the first tone given.

    Callers pass the most specific role first — the piece doing the thing before
    the squares it merely touches — so first wins is the right rule.
    """
    seen: dict = {}
    for mark in marks:
        seen.setdefault(mark.square, mark)
    return tuple(seen.values())


def _dedupe_arrows(arrows: Iterable[Arrow]) -> Tuple[Arrow, ...]:
    seen: dict = {}
    for arrow in arrows:
        seen.setdefault((arrow.origin, arrow.target), arrow)
    return tuple(seen.values())


def cue(
    *,
    actors: Sequence[SquareLike] = (),
    targets: Sequence[SquareLike] = (),
    friends: Sequence[SquareLike] = (),
    zone: Sequence[SquareLike] = (),
    arrows: Sequence[Arrow] = (),
    marks: Sequence[Mark] = (),
) -> Cue:
    """Build a cue from squares in any accepted form.

    The keyword names are the tones, so a call reads as the claim it draws:
    `cue(actors=[attacker], targets=[near, far], arrows=[...])`.
    """
    collected: List[Mark] = list(marks)
    for tone, squares in (
        ("actor", actors),
        ("target", targets),
        ("friend", friends),
        ("zone", zone),
    ):
        collected.extend(Mark(square_name(square), tone) for square in squares)
    return Cue(marks=_dedupe_marks(collected), arrows=_dedupe_arrows(arrows))


def arrow(origin: SquareLike, target: SquareLike, tone: str) -> Arrow:
    return Arrow(square_name(origin), square_name(target), tone)


def move_arrow(move: chess.Move, tone: str = "move") -> Arrow:
    return arrow(move.from_square, move.to_square, tone)


def move_cue(
    move: chess.Move, *, tone: str = "move", targets: Sequence[SquareLike] = ()
) -> Cue:
    """A move as geometry: where it goes, and what it lands on."""
    return cue(
        actors=[move.from_square],
        zone=[move.to_square],
        targets=targets,
        arrows=[move_arrow(move, tone)],
    )


def between(first: SquareLike, second: SquareLike) -> List[str]:
    """The empty squares a slider passes over, for lighting up a line."""
    start = first if isinstance(first, int) else chess.parse_square(first)
    end = second if isinstance(second, int) else chess.parse_square(second)
    return [chess.square_name(square) for square in chess.SquareSet.between(start, end)]


@dataclass(frozen=True)
class Insight:
    """A sentence and the geometry that backs it.

    Detectors that used to return a bare string return these instead, so the
    text and the drawing can never disagree about which pieces are involved.
    """

    text: str
    cue: Cue = field(default=EMPTY)

    def describe(self) -> str:
        return self.text
