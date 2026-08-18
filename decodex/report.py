"""Plain-text rendering of extracted facts.

This is deliberately template-driven. Every sentence is traceable to a fact
from `facts` or `game`, which is what keeps the output free of invented chess.
"""

from __future__ import annotations

from typing import List, Optional

import chess

from .facts import Contribution, PositionFacts
from .game import GameReview, MoveReview, Verdict

_VERDICT_MARK = {
    Verdict.BEST: "best",
    Verdict.EXCELLENT: "excellent",
    Verdict.GOOD: "good",
    Verdict.INACCURACY: "inaccuracy",
    Verdict.MISTAKE: "mistake",
    Verdict.BLUNDER: "blunder",
    Verdict.FORCED: "forced",
}


def side_name(color: Optional[chess.Color]) -> str:
    if color is None:
        return "Both sides"
    return "White" if color == chess.WHITE else "Black"


def format_eval(cp: Optional[int]) -> str:
    if cp is None:
        return "n/a"
    return f"{cp / 100:+.2f}"


def format_candidate_score(cp_white: int, mate: Optional[int]) -> str:
    if mate is not None:
        return f"mate in {abs(mate)}"
    return format_eval(cp_white)


def render_position(facts: PositionFacts) -> str:
    lines: List[str] = []
    who = side_name(facts.perspective)
    lines.append(f"=== Position analysis for {who} ===")
    lines.append(f"FEN            {facts.fen}")
    lines.append(f"Summary        {facts.assessment.describe()}")
    lines.append(f"Evaluation     {format_eval(facts.eval_cp)} (white's point of view)")
    if facts.free_tempo_view:
        lines.append(
            f"Note           it is {side_name(facts.turn)}'s turn, so {who}'s plans "
            "are shown as if handed the move."
        )
    if facts.note:
        lines.append(f"Note           {facts.note}")

    if facts.candidates:
        lines.append("")
        lines.append(f"Best moves for {who}")
        for candidate in facts.candidates:
            score = format_candidate_score(candidate.cp_white, candidate.mate)
            lines.append(f"  {candidate.rank}. {candidate.san:<8} {score:>12}")
            lines.append(f"     line: {candidate.pv_san}")

    if facts.purposes:
        best = facts.candidates[0].san if facts.candidates else "the best move"
        lines.append("")
        lines.append(f"{best} is good because it")
        lines.extend(f"  - {purpose.describe()}" for purpose in facts.purposes)

    lines.append("")
    lines.append("Threats")
    if facts.threat_before is not None:
        lines.append("  before: " + facts.threat_before.describe())
    else:
        lines.append("  before: no concrete threat found")
    if facts.threat_after_best is not None:
        best = facts.candidates[0].san if facts.candidates else "the best move"
        lines.append(f"  after {best}: {facts.threat_after_best.describe()}")

    if facts.neutralised:
        lines.append("  this move defuses:")
        lines.extend(f"    - {item.text}" for item in facts.neutralised)
    if facts.created:
        lines.append("  this move concedes:")
        lines.extend(f"    - {item.text}" for item in facts.created)

    if facts.tactics:
        lines.append("")
        lines.append("Tactics on the board")
        lines.extend(f"  - {item.text}" for item in facts.tactics)

    if facts.hanging:
        lines.append("")
        lines.append("Loose material (static exchange)")
        for item in facts.hanging[:4]:
            lines.append(
                f"  {item.piece_name} on {item.square} falls to "
                f"{item.capture_san} ({item.loss_cp / 100:+.2f})"
            )

    if facts.observations:
        lines.append("")
        lines.append("Pay attention to")
        lines.extend(f"  - {item.text}" for item in facts.observations)

    if facts.roles:
        lines.append("")
        lines.append(f"Piece roles for {who}")
        lines.extend(f"  - {role.describe()}" for role in facts.roles)

    if facts.concepts:
        lines.append("")
        lines.append("Concepts")
        lines.extend(f"  {concept.describe()}" for concept in facts.concepts)

    if facts.contributions:
        lines.append("")
        lines.append(f"Piece importance for {who} (NNUE removal ablation, in pawns)")
        lines.extend(_render_contributions(facts.contributions))

    return "\n".join(lines)


def _render_contributions(contributions: List[Contribution]) -> List[str]:
    lines: List[str] = []
    for item in contributions:
        row = f"  {item.piece_name:<7} {item.square}  {item.value:5.2f}"
        if item.delta is not None and abs(item.delta) >= 0.05:
            direction = "gains" if item.delta > 0 else "loses"
            row += f"   ({direction} {abs(item.delta):.2f} after the best move)"
        lines.append(row)
    return lines


def render_move_review(move: MoveReview, *, indent: str = "  ") -> List[str]:
    dots = "." if move.mover == chess.WHITE else "..."
    label = _VERDICT_MARK[move.verdict]
    if move.allowed_mate:
        outcome = f"mated in {abs(move.mate_after or 0)}"
    else:
        outcome = f"eval {format_eval(move.cp_after_white)}"
    lines = [f"{indent}{move.move_number}{dots} {move.san:<8} {label:<10} {outcome}"]
    if move.verdict.is_error and not move.played_best:
        if move.allowed_mate:
            detail = f"{indent}  {move.best_san} was better and avoided mate"
        else:
            detail = (
                f"{indent}  lost {move.loss_cp / 100:.2f}; "
                f"{move.best_san} was better"
            )
        if move.mate_missed is not None:
            detail += f" (mate in {move.mate_missed} was available)"
        lines.append(detail)
    return lines


# Eight blocks spanning a losing to a winning evaluation, for the graph column.
_BLOCKS = "▁▂▃▄▅▆▇█"
# The graph scales to the game it is drawing, between these bounds. A fixed
# scale flattens a quiet game into one repeated block; an unbounded one makes a
# half-pawn wobble look like a collapse.
_GRAPH_MIN_SPAN_CP = 100
_GRAPH_MAX_SPAN_CP = 500


def render_graph(review: GameReview, *, width: int = 64) -> List[str]:
    """A sparkline of the evaluation after each move, White's point of view."""
    if not review.moves:
        return []
    scores = [move.cp_after_white for move in review.moves]
    if len(scores) > width:
        # Keep the shape by sampling evenly rather than truncating the game.
        step = len(scores) / width
        scores = [scores[int(i * step)] for i in range(width)]

    span = max(
        _GRAPH_MIN_SPAN_CP, min(_GRAPH_MAX_SPAN_CP, max(abs(s) for s in scores))
    )
    bars = []
    for score in scores:
        clipped = max(-span, min(span, score))
        index = round((clipped + span) / (2 * span) * (len(_BLOCKS) - 1))
        bars.append(_BLOCKS[index])
    return [
        "Graph          " + "".join(bars),
        f"               white at the top, black at the bottom, "
        f"full height is {span / 100:.2f}",
    ]


def render_game(
    review: GameReview,
    colors: List[Optional[chess.Color]],
    headers: Optional[dict] = None,
    *,
    verbose: bool = False,
) -> str:
    lines: List[str] = ["=== Game review ==="]
    if headers:
        white = headers.get("White", "?")
        black = headers.get("Black", "?")
        lines.append(f"{white} vs {black}")
    lines.append(f"Result         {review.result}")
    lines.extend(render_graph(review))

    for color in colors:
        if color is None:
            continue
        lines.append("")
        lines.append(f"--- {side_name(color)} ---")
        accuracy = review.accuracy(color)
        average = review.average_loss(color)
        if accuracy is not None:
            lines.append(f"Clean moves    {accuracy:.0f}%")
        if average is not None:
            lines.append(f"Average loss   {average / 100:.2f} per move")
        counts = _verdict_counts(review, color)
        if counts:
            lines.append("Breakdown      " + ", ".join(counts))

        critical = review.critical(color)
        if critical:
            lines.append("Turning points")
            for move in critical:
                lines.extend(render_move_review(move, indent="  "))
        else:
            lines.append("Turning points none — no inaccuracies or worse")

        good = review.good_moves(color)
        if good:
            lines.append("Good moves")
            for move in good:
                dots = "." if move.mover == chess.WHITE else "..."
                lines.append(
                    f"  {move.move_number}{dots} {move.san:<8} "
                    f"clearly best, {move.swing_cp / 100:.2f} better than "
                    f"{move.second_best_san or 'the next move'}"
                )

    if verbose:
        lines.append("")
        lines.append("--- Every move ---")
        wanted = [c for c in colors if c is not None]
        for move in review.moves:
            if move.mover not in wanted:
                continue
            lines.extend(render_move_review(move))

    return "\n".join(lines)


def _verdict_counts(review: GameReview, color: chess.Color) -> List[str]:
    moves = review.for_side(color)
    counts: List[str] = []
    for verdict in Verdict:
        total = sum(1 for move in moves if move.verdict is verdict)
        if total:
            counts.append(f"{total} {_VERDICT_MARK[verdict]}")
    return counts
