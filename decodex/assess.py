"""Turning a number into the verdict sentence.

DecodeChess opens with a line like "White has a decisive advantage (4.48)". The
wording is a pure function of the evaluation, so it belongs here rather than in
any layer that could be tempted to editorialise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import chess

from .values import side_word

# Upper bound of each band, in centipawns, and the phrase for it. Under a third
# of a pawn is engine noise; past four pawns the game is decided with correct
# play, which is where DecodeChess also switches to "decisive".
_BANDS = (
    (30, "equal"),
    (80, "a slight edge"),
    (150, "a clear edge"),
    (300, "a serious advantage"),
    (400, "a winning advantage"),
)
_DECISIVE = "a decisive advantage"
_LEVEL = "equal"


@dataclass(frozen=True)
class Assessment:
    """Who stands better, by how much, and in what words."""

    cp_white: Optional[int]
    mate: Optional[int] = None

    @property
    def leader(self) -> Optional[chess.Color]:
        """The side that is better, or None when the position is level."""
        if self.mate is not None:
            return chess.WHITE if self.mate > 0 else chess.BLACK
        if self.cp_white is None:
            return None
        if abs(self.cp_white) <= _BANDS[0][0]:
            return None
        return chess.WHITE if self.cp_white > 0 else chess.BLACK

    @property
    def phrase(self) -> str:
        """The bare wording of the margin, e.g. "a decisive advantage"."""
        if self.cp_white is None and self.mate is None:
            return "no evaluation available"
        if self.mate is not None:
            winner = side_word(chess.WHITE if self.mate > 0 else chess.BLACK)
            return f"{winner} mates in {abs(self.mate)}"
        if self.leader is None:
            return _LEVEL
        magnitude = abs(self.cp_white or 0)
        for bound, phrase in _BANDS[1:]:
            if magnitude < bound:
                return phrase
        return _DECISIVE

    def describe(self) -> str:
        """The full sentence, as it appears at the top of a report."""
        if self.cp_white is None and self.mate is None:
            return "No evaluation available."
        if self.mate is not None:
            return f"{self.phrase}."
        score = (self.cp_white or 0) / 100
        if self.leader is None:
            return f"The position is balanced ({score:+.2f})."
        return f"{side_word(self.leader)} has {self.phrase} ({abs(score):.2f})."
