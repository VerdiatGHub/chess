"""Ground-truth fact extraction.

Everything here is derived from search or static rules, never inferred. The
language layer downstream is only allowed to verbalise these facts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import chess
import chess.engine

from .assess import Assessment
from .concepts import Concept, describe_concepts
from .engine import EvalTrace, RawEngine
from .motifs import describe_relations, describe_tactics
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

    @property
    def is_mate(self) -> bool:
        return self.mate is not None


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


@dataclass(frozen=True)
class Contribution:
    """A piece's importance, from Stockfish's own removal-ablation table."""

    square: str
    piece_name: str
    color: chess.Color
    value: float
    delta: Optional[float] = None


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
    neutralised: List[str] = field(default_factory=list)
    created: List[str] = field(default_factory=list)
    hanging: List[HangingPiece] = field(default_factory=list)
    contributions: List[Contribution] = field(default_factory=list)
    purposes: List[Purpose] = field(default_factory=list)
    roles: List[Role] = field(default_factory=list)
    concepts: List[Concept] = field(default_factory=list)
    observations: List[str] = field(default_factory=list)
    tactics: List[str] = field(default_factory=list)
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
    raw: RawEngine,
    *,
    perspective: chess.Color,
    depth: int = 18,
    threat_depth: int = 12,
    multipv: int = 3,
) -> PositionFacts:
    """Extract every fact we can justify about one position.

    When `perspective` is not the side to move, the position is analysed through
    a null move so that the requested side's own plans can be described.
    """
    limit = chess.engine.Limit(depth=depth)
    threat_limit = chess.engine.Limit(depth=threat_depth)

    trace = raw.eval_trace(board)
    facts = PositionFacts(
        fen=board.fen(),
        perspective=perspective,
        turn=board.turn,
        free_tempo_view=perspective != board.turn,
        eval_cp=trace.final_cp,
        contributions=contributions_from_trace(trace, perspective),
        roles=describe_roles(board, perspective),
        concepts=describe_concepts(board),
        observations=describe_relations(board),
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
                board, engine, threat_limit, free_tempo=False, baseline_cp=trace.final_cp
            )
            return facts
        view = hand_tempo(board)

    facts.tactics = describe_tactics(view)

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
            )
        )
        if rank == 1:
            facts.purposes = explain_move(view, pv)

    facts.hanging = find_hanging(view)
    facts.threat_before = free_tempo_threat(view, engine, threat_limit, trace.final_cp)

    if facts.candidates:
        after = view.copy(stack=False)
        after.push(chess.Move.from_uci(facts.candidates[0].uci))
        facts.threat_after_best = threat_of_side_to_move(
            after, engine, threat_limit, free_tempo=False, baseline_cp=trace.final_cp
        )
        facts.neutralised, facts.created = _diff_threats(
            view, after, facts.threat_before
        )
        facts.contributions = contributions_from_trace(
            trace, perspective, after=raw.eval_trace(after)
        )

    return facts


def _diff_threats(
    before: chess.Board,
    after: chess.Board,
    threat_before: Optional[Threat],
) -> tuple[List[str], List[str]]:
    """Which enemy targets the move takes off the board, and which it creates."""
    if not before.is_check():
        before_targets = {h.square: h for h in find_hanging(hand_tempo(before))}
    else:
        before_targets = {}
    after_targets = {h.square: h for h in find_hanging(after)}

    neutralised = [
        f"{item.piece_name} on {square} is no longer loose"
        for square, item in before_targets.items()
        if square not in after_targets
    ]
    created = [
        f"{item.piece_name} on {square} becomes loose ({item.loss_cp / 100:.2f})"
        for square, item in after_targets.items()
        if square not in before_targets
    ]
    if threat_before is not None and not threat_before.is_mate:
        still_legal = chess.Move.from_uci(threat_before.uci) in after.legal_moves
        if not still_legal:
            neutralised.append(f"{threat_before.san} is no longer available")
    return neutralised, created
