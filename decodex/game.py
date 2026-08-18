"""Whole-game analysis: classify every move and pick the moments worth reading."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional

import chess
import chess.engine
import chess.pgn

from .cues import Cue, cue, move_arrow
from .facts import MATE_SCORE, mate_in, score_cp


class Verdict(str, Enum):
    BEST = "best"
    EXCELLENT = "excellent"
    GOOD = "good"
    INACCURACY = "inaccuracy"
    MISTAKE = "mistake"
    BLUNDER = "blunder"
    FORCED = "forced"

    @property
    def is_error(self) -> bool:
        return self in (Verdict.INACCURACY, Verdict.MISTAKE, Verdict.BLUNDER)


# Thresholds are in centipawns lost from the mover's point of view.
_THRESHOLDS = (
    (300, Verdict.BLUNDER),
    (150, Verdict.MISTAKE),
    (50, Verdict.INACCURACY),
    (20, Verdict.GOOD),
)

# Losses are clamped here. Mate scores are ±100000, and a single missed mate
# would otherwise dominate every average.
MAX_LOSS_CP = 1000


def classify(loss_cp: int, *, was_only_move: bool, played_best: bool) -> Verdict:
    if was_only_move:
        return Verdict.FORCED
    if played_best:
        return Verdict.BEST
    for threshold, verdict in _THRESHOLDS:
        if loss_cp >= threshold:
            return verdict
    return Verdict.EXCELLENT


@dataclass(frozen=True)
class MoveReview:
    ply: int
    move_number: int
    mover: chess.Color
    san: str
    uci: str
    fen_before: str
    best_san: str
    best_uci: str
    cp_before_white: int
    cp_after_white: int
    loss_cp: int
    verdict: Verdict
    legal_count: int = 0
    second_best_cp_white: Optional[int] = None
    second_best_san: Optional[str] = None
    mate_missed: Optional[int] = None
    mate_after: Optional[int] = None

    @property
    def mover_name(self) -> str:
        return "White" if self.mover == chess.WHITE else "Black"

    @property
    def played_best(self) -> bool:
        return self.uci == self.best_uci

    @property
    def allowed_mate(self) -> bool:
        """True when this move leaves the mover being mated."""
        if self.mate_after is None:
            return False
        return (self.mate_after < 0) == (self.mover == chess.WHITE)

    @property
    def swing_cp(self) -> int:
        """How much better the best move was than the next best.

        This is what makes a good move noteworthy: a large swing means the
        alternatives all failed, so finding this one took work. Zero when the
        second choice was just as good, or when no alternative was searched.
        """
        if self.second_best_cp_white is None:
            return 0
        gap = (
            self.cp_before_white - self.second_best_cp_white
            if self.mover == chess.WHITE
            else self.second_best_cp_white - self.cp_before_white
        )
        return min(max(0, gap), MAX_LOSS_CP)

    @property
    def cue(self) -> Cue:
        """The move as played, and the engine's choice when it differed.

        Two arrows on one board is exactly the comparison a turning point is
        making, so they are drawn together rather than in sequence.
        """
        played = chess.Move.from_uci(self.uci)
        arrows = [move_arrow(played, "move")]
        if not self.played_best:
            arrows.append(move_arrow(chess.Move.from_uci(self.best_uci), "plan"))
        return cue(
            actors=[played.from_square], zone=[played.to_square], arrows=arrows
        )


@dataclass
class GameReview:
    moves: List[MoveReview] = field(default_factory=list)
    result: Optional[str] = None

    def for_side(self, color: Optional[chess.Color]) -> List[MoveReview]:
        if color is None:
            return list(self.moves)
        return [m for m in self.moves if m.mover == color]

    def accuracy(self, color: chess.Color) -> Optional[float]:
        """Share of moves that lost less than an inaccuracy's worth."""
        reviewed = [m for m in self.for_side(color) if m.verdict is not Verdict.FORCED]
        if not reviewed:
            return None
        clean = sum(1 for m in reviewed if not m.verdict.is_error)
        return 100.0 * clean / len(reviewed)

    def average_loss(self, color: chess.Color) -> Optional[float]:
        reviewed = [m for m in self.for_side(color) if m.verdict is not Verdict.FORCED]
        if not reviewed:
            return None
        return sum(m.loss_cp for m in reviewed) / len(reviewed)

    def critical(
        self, color: Optional[chess.Color] = None, limit: int = 3
    ) -> List[MoveReview]:
        errors = [m for m in self.for_side(color) if m.verdict.is_error]
        errors.sort(key=lambda m: m.loss_cp, reverse=True)
        return errors[:limit]

    def good_moves(
        self, color: Optional[chess.Color] = None, limit: int = 3
    ) -> List[MoveReview]:
        """Best moves that were not obvious: the ones worth taking credit for.

        A move only qualifies when the engine agrees it was best and there was a
        real choice. Recaptures and forced sequences are correct but say nothing
        about the player, so moves with only one or two legal alternatives and
        moves in already-decided positions are left out.
        """
        found = [
            move
            for move in self.for_side(color)
            if move.played_best
            and move.verdict is Verdict.BEST
            and move.legal_count > 2
            and move.swing_cp >= 50
            and abs(move.cp_before_white) < MAX_LOSS_CP
        ]
        # Rank by how much the alternatives would have cost, so the moves that
        # mattered most come first.
        found.sort(key=lambda m: m.swing_cp, reverse=True)
        return found[:limit]


def _loss_for_mover(mover: chess.Color, best_cp: int, actual_cp: int) -> int:
    """Centipawns thrown away, capped so a mate does not swamp the averages.

    Raw mate scores are ±100000, and letting those through would make a single
    missed mate dominate every aggregate. One clear blunder's worth is enough to
    rank the move as bad.
    """
    signed = best_cp - actual_cp if mover == chess.WHITE else actual_cp - best_cp
    return min(max(0, signed), MAX_LOSS_CP)


def review_game(
    game_board: chess.Board,
    moves: List[chess.Move],
    engine: chess.engine.SimpleEngine,
    *,
    depth: int = 14,
    progress: Optional[Callable[[int, int], None]] = None,
) -> GameReview:
    """Score every move against the engine's preference for that position."""
    limit = chess.engine.Limit(depth=depth)
    board = game_board.copy()
    review = GameReview()

    for index, played in enumerate(moves):
        legal_count = board.legal_moves.count()
        # Two lines, so the gap between the best move and the next best is known.
        # That gap is what separates a hard move to find from an obvious one.
        infos = engine.analyse(board, limit, multipv=2)
        info = infos[0]
        pv = info.get("pv") or [played]
        best_move = pv[0]
        cp_before = score_cp(info)
        best_mate = mate_in(info)
        second_best = score_cp(infos[1]) if len(infos) > 1 else None
        second_best_pv = infos[1].get("pv") if len(infos) > 1 else None

        san = board.san(played)
        best_san = board.san(best_move)
        second_best_san = (
            board.san(second_best_pv[0]) if second_best_pv else None
        )
        fen_before = board.fen()
        mover = board.turn
        move_number = board.fullmove_number

        board.push(played)
        mate_after: Optional[int] = None
        if board.is_game_over():
            # A move that ends the game cannot have walked into mate: the mover
            # either delivered it or drew, so there is no mate against them.
            cp_after = _terminal_cp(board)
        else:
            after_info = engine.analyse(board, limit)
            cp_after = score_cp(after_info)
            mate_after = mate_in(after_info)

        loss = _loss_for_mover(mover, cp_before, cp_after)
        verdict = classify(
            loss,
            was_only_move=legal_count == 1,
            played_best=played == best_move,
        )
        mate_missed = None
        if best_mate is not None and played != best_move:
            mover_had_mate = (best_mate > 0) == (mover == chess.WHITE)
            if mover_had_mate:
                mate_missed = abs(best_mate)

        review.moves.append(
            MoveReview(
                ply=index + 1,
                move_number=move_number,
                mover=mover,
                san=san,
                uci=played.uci(),
                fen_before=fen_before,
                best_san=best_san,
                best_uci=best_move.uci(),
                cp_before_white=cp_before,
                cp_after_white=cp_after,
                loss_cp=loss,
                verdict=verdict,
                legal_count=legal_count,
                second_best_cp_white=second_best,
                second_best_san=second_best_san,
                mate_missed=mate_missed,
                mate_after=mate_after,
            )
        )
        if progress is not None:
            progress(index + 1, len(moves))

    review.result = board.result() if board.is_game_over() else "*"
    return review


def _terminal_cp(board: chess.Board) -> int:
    if board.is_checkmate():
        # The side that just moved delivered mate.
        return -MATE_SCORE if board.turn == chess.WHITE else MATE_SCORE
    return 0


def load_pgn(path: str) -> tuple[chess.Board, List[chess.Move], dict]:
    with open(path, encoding="utf-8") as handle:
        return _read_game(handle, path)


def load_pgn_text(text: str) -> tuple[chess.Board, List[chess.Move], dict]:
    return _read_game(io.StringIO(text), "the supplied PGN")


def _read_game(handle, label: str) -> tuple[chess.Board, List[chess.Move], dict]:
    game = chess.pgn.read_game(handle)
    if game is None:
        raise ValueError(f"No game found in {label}")
    board = game.board()
    return board, list(game.mainline_moves()), dict(game.headers)


def moves_from_uci(board: chess.Board, tokens: List[str]) -> List[chess.Move]:
    """Parse a move list, accepting UCI and SAN interchangeably.

    The caller's board is left untouched.
    """
    played: List[chess.Move] = []
    probe = board.copy()
    for token in tokens:
        try:
            move = probe.parse_uci(token)
        except ValueError:
            move = probe.parse_san(token)
        played.append(move)
        probe.push(move)
    return played
