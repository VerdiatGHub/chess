"""Ground-truth fact extraction.

Everything here is derived from search or static rules, never inferred. The
language layer downstream is only allowed to verbalise these facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import chess
import chess.engine

from .assess import Assessment
from .concepts import Concept, describe_concepts
from .cues import Cue, Insight, arrow, cue, move_cue
from .engine import EvalTrace, RawEngine
from .motifs import relation_insights, tactic_insights
from .plans import Purpose, explain_move
from .roles import Role, describe_roles
from .values import MATE_SCORE, PIECE_VALUE, piece_name, with_turn

# Kept under the old name because SEE is the only place these are used as
# exchange values rather than as a general ranking.
SEE_VALUES = PIECE_VALUE


def see(board: chess.Board, move: chess.Move) -> int:
    """Static exchange evaluation for `move`, in centipawns for the mover.

    Standard swap-off with pruning: the recapturing side may always decline,
    so recursive values are floored at zero.
    """
    captured = _captured_value(board, move)
    if captured == 0 and not move.promotion:
        return 0
    after = board.copy(stack=False)
    after.push(move)
    return captured - _recapture_value(after, move.to_square)


def _captured_value(board: chess.Board, move: chess.Move) -> int:
    if board.is_en_passant(move):
        return SEE_VALUES[chess.PAWN]
    victim = board.piece_type_at(move.to_square)
    return SEE_VALUES[victim] if victim else 0


def _recapture_value(board: chess.Board, square: chess.Square) -> int:
    recaptures = [
        move
        for move in board.legal_moves
        if move.to_square == square and board.is_capture(move)
    ]
    if not recaptures:
        return 0
    cheapest = min(
        recaptures,
        key=lambda move: SEE_VALUES[board.piece_type_at(move.from_square)],
    )
    captured = _captured_value(board, cheapest)
    after = board.copy(stack=False)
    after.push(cheapest)
    return max(0, captured - _recapture_value(after, square))


def hand_tempo(board: chess.Board) -> chess.Board:
    """Return the same position with the turn flipped."""
    return with_turn(board, not board.turn)


def score_cp(info: chess.engine.InfoDict) -> int:
    """Centipawn score from white's point of view, mates as large finite values."""
    score = info["score"]
    assert isinstance(score, chess.engine.PovScore)
    return score.white().score(mate_score=MATE_SCORE)


def mate_in(info: chess.engine.InfoDict) -> Optional[int]:
    score = info["score"]
    assert isinstance(score, chess.engine.PovScore)
    return score.white().mate()


@dataclass(frozen=True)
class Candidate:
    rank: int
    uci: str
    san: str
    cp_white: int
    mate: Optional[int]
    pv_san: str
    cue: Cue = field(default_factory=Cue)

    @property
    def is_mate(self) -> bool:
        return self.mate is not None


def candidate_cue(board: chess.Board, pv: Sequence[chess.Move], *, depth: int = 3) -> Cue:
    """The move to play, then the line it leads to.

    The continuation is drawn as plans rather than moves, because only the first
    move is the recommendation; the rest is what the search expects to follow.
    """
    if not pv:
        return Cue()
    first = pv[0]
    arrows = [arrow(first.from_square, first.to_square, "move")]
    arrows += [
        arrow(move.from_square, move.to_square, "plan") for move in pv[1:depth]
    ]
    return cue(actors=[first.from_square], zone=[first.to_square], arrows=arrows)


@dataclass(frozen=True)
class Threat:
    """What a side intends to do next.

    `free_tempo` distinguishes the two ways this is measured: handing a side an
    extra move via a null move (used to ask "what are they aiming at?"), versus
    simply reading their best move when it is genuinely their turn.
    """

    mover: chess.Color
    uci: str
    san: str
    cp_white: int
    mate: Optional[int]
    free_tempo: bool
    captures: Optional[str] = None
    gain_cp: int = 0
    cue: Cue = field(default_factory=Cue)

    @property
    def is_mate(self) -> bool:
        return self.mate is not None

    def describe(self) -> str:
        who = "White" if self.mover == chess.WHITE else "Black"
        if self.is_mate:
            return f"{who} threatens {self.san} — mate in {abs(self.mate or 0)}"
        if self.captures:
            return f"{who} threatens {self.san}, winning the {self.captures}"
        # A gain is only worth quoting when the move actually improves things;
        # in a lost position the engine's best try still evaluates badly.
        if self.gain_cp >= 50:
            return f"{who} threatens {self.san} (gains {self.gain_cp / 100:.2f})"
        return f"{who} intends {self.san}, with nothing concrete yet"


@dataclass(frozen=True)
class HangingPiece:
    square: str
    piece_name: str
    color: chess.Color
    loss_cp: int
    capture_san: str
    cue: Cue = field(default_factory=Cue)


@dataclass(frozen=True)
class Contribution:
    """A piece's importance, from Stockfish's own removal-ablation table."""

    square: str
    piece_name: str
    color: chess.Color
    value: float
    delta: Optional[float] = None

    @property
    def cue(self) -> Cue:
        return cue(actors=[self.square])


@dataclass
class PositionFacts:
    fen: str
    perspective: chess.Color
    turn: chess.Color
    free_tempo_view: bool
    eval_cp: Optional[int]
    candidates: List[Candidate] = field(default_factory=list)
    threat_before: Optional[Threat] = None
    threat_after_best: Optional[Threat] = None
    neutralised: List[Insight] = field(default_factory=list)
    created: List[Insight] = field(default_factory=list)
    hanging: List[HangingPiece] = field(default_factory=list)
    contributions: List[Contribution] = field(default_factory=list)
    purposes: List[Purpose] = field(default_factory=list)
    roles: List[Role] = field(default_factory=list)
    concepts: List[Concept] = field(default_factory=list)
    observations: List[Insight] = field(default_factory=list)
    tactics: List[Insight] = field(default_factory=list)
    note: Optional[str] = None

    @property
    def assessment(self) -> Assessment:
        mate = self.candidates[0].mate if self.candidates else None
        return Assessment(cp_white=self.eval_cp, mate=mate)


def find_hanging(board: chess.Board) -> List[HangingPiece]:
    """Pieces the side to move can win by force, per static exchange."""
    found: List[HangingPiece] = []
    for move in board.legal_moves:
        if not board.is_capture(move):
            continue
        gain = see(board, move)
        if gain < SEE_VALUES[chess.PAWN]:
            continue
        victim = board.piece_type_at(move.to_square)
        if victim is None:
            continue
        found.append(
            HangingPiece(
                square=chess.square_name(move.to_square),
                piece_name=chess.piece_name(victim),
                color=not board.turn,
                loss_cp=gain,
                capture_san=board.san(move),
                cue=move_cue(move, targets=[move.to_square]),
            )
        )
    found.sort(key=lambda h: h.loss_cp, reverse=True)
    # Keep the best capture per target square.
    seen: set[str] = set()
    unique: List[HangingPiece] = []
    for item in found:
        if item.square in seen:
            continue
        seen.add(item.square)
        unique.append(item)
    return unique


def threat_of_side_to_move(
    board: chess.Board,
    engine: chess.engine.SimpleEngine,
    limit: chess.engine.Limit,
    *,
    free_tempo: bool,
    baseline_cp: Optional[int] = None,
) -> Optional[Threat]:
    if board.is_game_over():
        return None
    info = engine.analyse(board, limit)
    pv = info.get("pv")
    if not pv:
        return None
    move = pv[0]
    captures = None
    if board.is_capture(move) and see(board, move) > 0:
        victim = board.piece_type_at(move.to_square)
        captures = chess.piece_name(victim) if victim else "pawn"
    cp = score_cp(info)
    gain = 0
    if baseline_cp is not None:
        gain = cp - baseline_cp if board.turn == chess.WHITE else baseline_cp - cp
    return Threat(
        mover=board.turn,
        uci=move.uci(),
        san=board.san(move),
        cp_white=cp,
        mate=mate_in(info),
        free_tempo=free_tempo,
        captures=captures,
        gain_cp=gain,
        cue=move_cue(
            move,
            tone="threat",
            targets=[move.to_square] if board.piece_at(move.to_square) else [],
        ),
    )


def free_tempo_threat(
    board: chess.Board,
    engine: chess.engine.SimpleEngine,
    limit: chess.engine.Limit,
    baseline_cp: Optional[int] = None,
) -> Optional[Threat]:
    """What the side *not* to move is aiming at, via a null move.

    A null move is meaningless while in check, since the check must be answered
    first, so no threat is reported there.
    """
    if board.is_check() or board.is_game_over():
        return None
    return threat_of_side_to_move(
        hand_tempo(board), engine, limit, free_tempo=True, baseline_cp=baseline_cp
    )


def contributions_from_trace(
    trace: EvalTrace,
    color: chess.Color,
    after: Optional[EvalTrace] = None,
    limit: int = 6,
) -> List[Contribution]:
    result: List[Contribution] = []
    for piece in trace.for_color(color)[:limit]:
        delta = None
        if after is not None:
            later = after.piece_values.get(piece.square)
            if later is not None and later.value is not None and later.symbol == piece.symbol:
                delta = round(abs(later.value) - piece.magnitude, 2)
        result.append(
            Contribution(
                square=piece.square,
                piece_name=piece_name(piece.symbol),
                color=piece.color,
                value=round(piece.magnitude, 2),
                delta=delta,
            )
        )
    return result


def analyse_position(
    board: chess.Board,
    engine: chess.engine.SimpleEngine,
    raw: Optional[RawEngine] = None,
    *,
    perspective: chess.Color,
    depth: int = 18,
    threat_depth: int = 12,
    multipv: int = 3,
) -> PositionFacts:
    """Extract every fact we can justify about one position.

    When `perspective` is not the side to move, the position is analysed through
    a null move so that the requested side's own plans can be described.

    `raw` is optional. It provides the NNUE piece-importance table, which needs
    Stockfish's non-standard `eval` command on a second process; without it that
    one panel is omitted and everything else is unaffected. Small hosts cannot
    afford the second process, so this has to degrade rather than fail.
    """
    limit = chess.engine.Limit(depth=depth)
    threat_limit = chess.engine.Limit(depth=threat_depth)

    trace = raw.eval_trace(board) if raw is not None else None
    eval_cp = trace.final_cp if trace is not None else None
    facts = PositionFacts(
        fen=board.fen(),
        perspective=perspective,
        turn=board.turn,
        free_tempo_view=perspective != board.turn,
        eval_cp=eval_cp,
        contributions=(
            contributions_from_trace(trace, perspective) if trace is not None else []
        ),
        roles=describe_roles(board, perspective),
        concepts=describe_concepts(board),
        observations=relation_insights(board),
    )

    if board.is_game_over():
        facts.note = f"Game already over: {board.result()}"
        return facts

    view = board
    if facts.free_tempo_view:
        if board.is_check():
            facts.note = (
                "Side to move is in check, so the other side cannot be handed a "
                "free tempo; showing threats only."
            )
            facts.threat_before = threat_of_side_to_move(
                board, engine, threat_limit, free_tempo=False, baseline_cp=eval_cp
            )
            return facts
        view = hand_tempo(board)

    facts.tactics = tactic_insights(view)

    infos = engine.analyse(view, limit, multipv=multipv)
    for rank, info in enumerate(infos, start=1):
        pv = info.get("pv")
        if not pv:
            continue
        facts.candidates.append(
            Candidate(
                rank=rank,
                uci=pv[0].uci(),
                san=view.san(pv[0]),
                cp_white=score_cp(info),
                mate=mate_in(info),
                pv_san=view.variation_san(pv[:8]),
                cue=candidate_cue(view, pv),
            )
        )
        if rank == 1:
            facts.purposes = explain_move(view, pv)

    # Without the eval trace there is still a number to anchor threats against:
    # the score of the best line, which the search has already produced.
    if facts.eval_cp is None and facts.candidates:
        facts.eval_cp = facts.candidates[0].cp_white
        eval_cp = facts.eval_cp

    facts.hanging = find_hanging(view)
    facts.threat_before = free_tempo_threat(view, engine, threat_limit, eval_cp)

    if facts.candidates:
        after = view.copy(stack=False)
        after.push(chess.Move.from_uci(facts.candidates[0].uci))
        facts.threat_after_best = threat_of_side_to_move(
            after, engine, threat_limit, free_tempo=False, baseline_cp=eval_cp
        )
        facts.neutralised, facts.created = _diff_threats(
            view, after, facts.threat_before
        )
        if trace is not None and raw is not None:
            facts.contributions = contributions_from_trace(
                trace, perspective, after=raw.eval_trace(after)
            )

    return facts


def _diff_threats(
    before: chess.Board,
    after: chess.Board,
    threat_before: Optional[Threat],
) -> tuple[List[Insight], List[Insight]]:
    """Which enemy targets the move takes off the board, and which it creates."""
    if not before.is_check():
        before_targets = {h.square: h for h in find_hanging(hand_tempo(before))}
    else:
        before_targets = {}
    after_targets = {h.square: h for h in find_hanging(after)}

    neutralised = [
        Insight(
            f"{item.piece_name} on {square} is no longer loose",
            cue(friends=[square]),
        )
        for square, item in before_targets.items()
        if square not in after_targets
    ]
    created = [
        Insight(
            f"{item.piece_name} on {square} becomes loose ({item.loss_cp / 100:.2f})",
            item.cue,
        )
        for square, item in after_targets.items()
        if square not in before_targets
    ]
    if threat_before is not None and not threat_before.is_mate:
        still_legal = chess.Move.from_uci(threat_before.uci) in after.legal_moves
        if not still_legal:
            neutralised.append(
                Insight(
                    f"{threat_before.san} is no longer available",
                    threat_before.cue,
                )
            )
    return neutralised, created
