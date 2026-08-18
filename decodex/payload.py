"""Facts as plain data, for the HTTP layer.

The report module renders facts as text for a terminal. The web UI needs the same
facts as JSON so the browser can lay them out — and, because every fact carries
the squares it was derived from, draw them on the board. Both read the same
dataclasses, so neither can invent anything the other does not have.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import chess

from .concepts import Concept
from .cues import Cue, Insight
from .facts import PositionFacts
from .game import GameReview, MoveReview
from .values import side_word


def _cue(cue: Optional[Cue]) -> Dict[str, Any]:
    """A cue as the browser wants it: squares to light, arrows to draw."""
    if cue is None:
        return {"marks": [], "arrows": []}
    return {
        "marks": [{"square": mark.square, "tone": mark.tone} for mark in cue.marks],
        "arrows": [
            {"from": item.origin, "to": item.target, "tone": item.tone}
            for item in cue.arrows
        ],
    }


def _insights(items: List[Insight]) -> List[Dict[str, Any]]:
    return [{"text": item.text, "cue": _cue(item.cue)} for item in items]


def _threat(threat) -> Optional[Dict[str, Any]]:
    if threat is None:
        return None
    return {
        "mover": side_word(threat.mover),
        "san": threat.san,
        "text": threat.describe(),
        "isMate": threat.is_mate,
        "cue": _cue(threat.cue),
    }


def _concepts(concepts: List[Concept]) -> List[Dict[str, Any]]:
    return [
        {
            "name": concept.name,
            "detail": concept.detail,
            "favours": side_word(concept.favours) if concept.favours is not None else None,
            "text": concept.describe(),
            "cue": _cue(concept.cue()),
        }
        for concept in concepts
    ]


def position_payload(facts: PositionFacts) -> Dict[str, Any]:
    return {
        "fen": facts.fen,
        "perspective": side_word(facts.perspective),
        "turn": side_word(facts.turn),
        "freeTempoView": facts.free_tempo_view,
        "evalCp": facts.eval_cp,
        "summary": facts.assessment.describe(),
        "note": facts.note,
        "candidates": [
            {
                "rank": candidate.rank,
                "san": candidate.san,
                "uci": candidate.uci,
                "evalCp": candidate.cp_white,
                "mate": candidate.mate,
                "line": candidate.pv_san,
                "linePlies": [
                    {
                        "ply": ply.ply,
                        "moveNumber": ply.move_number,
                        "color": side_word(ply.color),
                        "san": ply.san,
                        "uci": ply.uci,
                        "fenBefore": ply.fen_before,
                        "fenAfter": ply.fen_after,
                        "cue": _cue(ply.cue),
                        "purposes": [
                            {"text": purpose.describe(), "cue": _cue(purpose.cue)}
                            for purpose in ply.purposes
                        ],
                        "weaknesses": [
                            {"text": weakness.describe(), "cue": _cue(weakness.cue)}
                            for weakness in ply.weaknesses
                        ],
                    }
                    for ply in candidate.line
                ],
                "cue": _cue(candidate.cue),
            }
            for candidate in facts.candidates
        ],
        "purposes": [
            {"text": purpose.describe(), "cue": _cue(purpose.cue)}
            for purpose in facts.purposes
        ],
        "threatBefore": _threat(facts.threat_before),
        "threatAfterBest": _threat(facts.threat_after_best),
        "neutralised": _insights(facts.neutralised),
        "created": _insights(facts.created),
        "tactics": _insights(facts.tactics),
        "hanging": [
            {
                "square": item.square,
                "piece": item.piece_name,
                "captureSan": item.capture_san,
                "lossCp": item.loss_cp,
                "cue": _cue(item.cue),
            }
            for item in facts.hanging
        ],
        "observations": _insights(facts.observations),
        "roles": [
            {"text": role.describe(), "cue": _cue(role.cue())} for role in facts.roles
        ],
        "concepts": _concepts(facts.concepts),
        "contributions": [
            {
                "square": item.square,
                "piece": item.piece_name,
                "value": item.value,
                "delta": item.delta,
                "cue": _cue(item.cue),
            }
            for item in facts.contributions
        ],
    }


def _move_payload(move: MoveReview) -> Dict[str, Any]:
    return {
        "ply": move.ply,
        "moveNumber": move.move_number,
        "mover": side_word(move.mover),
        "san": move.san,
        "uci": move.uci,
        "fenBefore": move.fen_before,
        "bestSan": move.best_san,
        "playedBest": move.played_best,
        "verdict": move.verdict.value,
        "isError": move.verdict.is_error,
        "lossCp": move.loss_cp,
        "swingCp": move.swing_cp,
        "evalCp": move.cp_after_white,
        "allowedMate": move.allowed_mate,
        "mateAfter": move.mate_after,
        "mateMissed": move.mate_missed,
        "secondBestSan": move.second_best_san,
        "cue": _cue(move.cue),
    }


def _side_payload(review: GameReview, color: chess.Color) -> Dict[str, Any]:
    accuracy = review.accuracy(color)
    average = review.average_loss(color)
    return {
        "side": side_word(color),
        "cleanPercent": round(accuracy, 1) if accuracy is not None else None,
        "averageLossCp": round(average, 1) if average is not None else None,
        "breakdown": _breakdown(review, color),
        "turningPoints": [_move_payload(m) for m in review.critical(color)],
        "goodMoves": [_move_payload(m) for m in review.good_moves(color)],
    }


def _breakdown(review: GameReview, color: chess.Color) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for move in review.for_side(color):
        counts[move.verdict.value] = counts.get(move.verdict.value, 0) + 1
    return counts


def game_payload(
    review: GameReview,
    colors: List[chess.Color],
    headers: Optional[dict] = None,
) -> Dict[str, Any]:
    return {
        "result": review.result,
        "white": (headers or {}).get("White"),
        "black": (headers or {}).get("Black"),
        "graph": [move.cp_after_white for move in review.moves],
        "sides": [_side_payload(review, color) for color in colors],
        "moves": [_move_payload(move) for move in review.moves],
    }
