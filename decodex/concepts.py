"""Structural features of the position.

DecodeChess groups these under Concepts. Each one is a countable property of the
board — material, pawn structure, king shelter, space, development — so the claim
is arithmetic rather than judgement. Where a feature favours a side, that is
stated; where it is level, it is left out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import chess

from .values import PIECE_VALUE, side_word


@dataclass(frozen=True)
class Concept:
    """A named structural feature, with the side it favours."""

    name: str
    detail: str
    favours: Optional[chess.Color] = None

    def describe(self) -> str:
        if self.favours is None:
            return f"{self.name}: {self.detail}"
        return f"{self.name}: {self.detail} ({side_word(self.favours)})"


def material_count(board: chess.Board, color: chess.Color) -> int:
    """Total value of a side's non-king material, in centipawns."""
    return sum(
        PIECE_VALUE[piece.piece_type]
        for piece in board.piece_map().values()
        if piece.color == color and piece.piece_type != chess.KING
    )


def _pawn_files(board: chess.Board, color: chess.Color) -> Dict[int, List[int]]:
    files: Dict[int, List[int]] = {}
    for square in board.pieces(chess.PAWN, color):
        files.setdefault(chess.square_file(square), []).append(chess.square_rank(square))
    return files


def doubled_pawns(board: chess.Board, color: chess.Color) -> List[str]:
    return [
        chess.FILE_NAMES[file_index]
        for file_index, ranks in sorted(_pawn_files(board, color).items())
        if len(ranks) > 1
    ]


def isolated_pawns(board: chess.Board, color: chess.Color) -> List[str]:
    files = _pawn_files(board, color)
    isolated = []
    for file_index, ranks in sorted(files.items()):
        neighbours = {file_index - 1, file_index + 1} & files.keys()
        if not neighbours:
            isolated.extend(
                chess.square_name(chess.square(file_index, rank)) for rank in sorted(ranks)
            )
    return isolated


def passed_pawns(board: chess.Board, color: chess.Color) -> List[str]:
    """Pawns with no enemy pawn ahead on their file or either neighbour."""
    forward = 1 if color == chess.WHITE else -1
    enemy_files = _pawn_files(board, not color)
    passed = []
    for square in board.pieces(chess.PAWN, color):
        file_index = chess.square_file(square)
        rank = chess.square_rank(square)
        blocked = False
        for offset in (-1, 0, 1):
            neighbour = file_index + offset
            for enemy_rank in enemy_files.get(neighbour, []):
                if (enemy_rank - rank) * forward > 0:
                    blocked = True
                    break
            if blocked:
                break
        if not blocked:
            passed.append(chess.square_name(square))
    return sorted(passed)


def king_shelter_count(board: chess.Board, color: chess.Color) -> int:
    """Own pawns on the three files in front of the king, within two ranks."""
    king = board.king(color)
    if king is None:
        return 0
    forward = 1 if color == chess.WHITE else -1
    king_file = chess.square_file(king)
    king_rank = chess.square_rank(king)
    count = 0
    for file_offset in (-1, 0, 1):
        file_index = king_file + file_offset
        if not 0 <= file_index <= 7:
            continue
        for rank_offset in (1, 2):
            rank_index = king_rank + forward * rank_offset
            if not 0 <= rank_index <= 7:
                continue
            piece = board.piece_at(chess.square(file_index, rank_index))
            if piece is not None and piece.color == color and piece.piece_type == chess.PAWN:
                count += 1
    return count


def king_attackers(board: chess.Board, color: chess.Color) -> int:
    """Enemy pieces bearing on the squares around a king."""
    king = board.king(color)
    if king is None:
        return 0
    zone = set(board.attacks(king)) | {king}
    attackers: set = set()
    for square in zone:
        attackers |= set(board.attackers(not color, square))
    return len(attackers)


def space(board: chess.Board, color: chess.Color) -> int:
    """Squares on the far half of the board that a side's pawns control."""
    far_ranks = range(4, 8) if color == chess.WHITE else range(0, 4)
    controlled = set()
    for square in board.pieces(chess.PAWN, color):
        for target in board.attacks(square):
            if chess.square_rank(target) in far_ranks:
                controlled.add(target)
    return len(controlled)


def undeveloped(board: chess.Board, color: chess.Color) -> List[str]:
    """Minor pieces and rooks still on their starting squares."""
    home_rank = 0 if color == chess.WHITE else 7
    starts = {
        chess.square(0, home_rank): chess.ROOK,
        chess.square(1, home_rank): chess.KNIGHT,
        chess.square(2, home_rank): chess.BISHOP,
        chess.square(5, home_rank): chess.BISHOP,
        chess.square(6, home_rank): chess.KNIGHT,
        chess.square(7, home_rank): chess.ROOK,
    }
    idle = []
    for square, piece_type in starts.items():
        piece = board.piece_at(square)
        if piece is not None and piece.color == color and piece.piece_type == piece_type:
            idle.append(chess.square_name(square))
    return sorted(idle)


def _favour(
    white_value: int, black_value: int, *, higher_is_better: bool = True
) -> Optional[chess.Color]:
    if white_value == black_value:
        return None
    white_ahead = white_value > black_value
    if not higher_is_better:
        white_ahead = not white_ahead
    return chess.WHITE if white_ahead else chess.BLACK


def describe_concepts(board: chess.Board, *, limit: int = 8) -> List[Concept]:
    """Every structural feature that favours one side.

    Level features are dropped rather than reported as level: a list where half
    the entries say "equal" buries the ones that matter.
    """
    concepts: List[Concept] = []

    white_material = material_count(board, chess.WHITE)
    black_material = material_count(board, chess.BLACK)
    if white_material != black_material:
        margin = abs(white_material - black_material) / 100
        leader = chess.WHITE if white_material > black_material else chess.BLACK
        concepts.append(
            Concept(name="Material", detail=f"{margin:.2f} ahead", favours=leader)
        )

    for label, finder, weakness in (
        ("Doubled pawns", doubled_pawns, True),
        ("Isolated pawns", isolated_pawns, True),
        ("Passed pawns", passed_pawns, False),
    ):
        white = finder(board, chess.WHITE)
        black = finder(board, chess.BLACK)
        if not white and not black:
            continue
        parts = []
        if white:
            parts.append(f"White {', '.join(white)}")
        if black:
            parts.append(f"Black {', '.join(black)}")
        favours = None
        if bool(white) != bool(black):
            has_it = chess.WHITE if white else chess.BLACK
            favours = (not has_it) if weakness else has_it
        concepts.append(Concept(name=label, detail="; ".join(parts), favours=favours))

    white_shelter = king_shelter_count(board, chess.WHITE)
    black_shelter = king_shelter_count(board, chess.BLACK)
    white_pressure = king_attackers(board, chess.WHITE)
    black_pressure = king_attackers(board, chess.BLACK)
    if (white_shelter, white_pressure) != (black_shelter, black_pressure):
        concepts.append(
            Concept(
                name="King safety",
                detail=(
                    f"shelter pawns {white_shelter} vs {black_shelter}, "
                    f"attackers on the king {white_pressure} vs {black_pressure}"
                ),
                favours=_favour(
                    white_shelter - white_pressure, black_shelter - black_pressure
                ),
            )
        )

    white_space = space(board, chess.WHITE)
    black_space = space(board, chess.BLACK)
    if white_space != black_space:
        concepts.append(
            Concept(
                name="Space",
                detail=f"pawn-controlled squares in enemy territory {white_space} vs {black_space}",
                favours=_favour(white_space, black_space),
            )
        )

    white_idle = undeveloped(board, chess.WHITE)
    black_idle = undeveloped(board, chess.BLACK)
    if len(white_idle) != len(black_idle):
        concepts.append(
            Concept(
                name="Development",
                detail=(
                    f"still at home: White {len(white_idle)}, Black {len(black_idle)}"
                ),
                favours=_favour(
                    len(white_idle), len(black_idle), higher_is_better=False
                ),
            )
        )

    return concepts[:limit]
