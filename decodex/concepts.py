"""Structural features of the position.

DecodeChess groups these under Concepts. Each one is a countable property of the
board — material, pawn structure, king shelter, space, development — so the claim
is arithmetic rather than judgement. Where a feature favours a side, that is
stated; where it is level, it is left out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import chess

from .cues import Cue, cue
from .values import PIECE_VALUE, side_word


@dataclass(frozen=True)
class Concept:
    """A named structural feature, with the side it favours.

    `white_squares` and `black_squares` are the squares the count was taken
    from, so hovering the concept shows the reader exactly what was counted
    rather than asking them to trust the number.
    """

    name: str
    detail: str
    favours: Optional[chess.Color] = None
    white_squares: Tuple[chess.Square, ...] = ()
    black_squares: Tuple[chess.Square, ...] = ()

    def describe(self) -> str:
        if self.favours is None:
            return f"{self.name}: {self.detail}"
        return f"{self.name}: {self.detail} ({side_word(self.favours)})"

    def cue(self) -> Cue:
        """Both sides' squares, with the favoured side's marked as the actors."""
        if self.favours == chess.BLACK:
            return cue(actors=self.black_squares, zone=self.white_squares)
        return cue(actors=self.white_squares, zone=self.black_squares)


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


def _names(squares: Sequence[chess.Square]) -> List[str]:
    """Square names in reading order, which for a1..h8 is plain alphabetical."""
    return sorted(chess.square_name(square) for square in squares)


def doubled_pawn_squares(board: chess.Board, color: chess.Color) -> List[chess.Square]:
    return [
        chess.square(file_index, rank)
        for file_index, ranks in sorted(_pawn_files(board, color).items())
        if len(ranks) > 1
        for rank in sorted(ranks)
    ]


def doubled_pawns(board: chess.Board, color: chess.Color) -> List[str]:
    return [
        chess.FILE_NAMES[file_index]
        for file_index, ranks in sorted(_pawn_files(board, color).items())
        if len(ranks) > 1
    ]


def isolated_pawn_squares(board: chess.Board, color: chess.Color) -> List[chess.Square]:
    files = _pawn_files(board, color)
    isolated = []
    for file_index, ranks in sorted(files.items()):
        neighbours = {file_index - 1, file_index + 1} & files.keys()
        if not neighbours:
            isolated.extend(chess.square(file_index, rank) for rank in sorted(ranks))
    return isolated


def isolated_pawns(board: chess.Board, color: chess.Color) -> List[str]:
    return _names(isolated_pawn_squares(board, color))


def passed_pawn_squares(board: chess.Board, color: chess.Color) -> List[chess.Square]:
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
            passed.append(square)
    return passed


def passed_pawns(board: chess.Board, color: chess.Color) -> List[str]:
    return _names(passed_pawn_squares(board, color))


def king_shelter_squares(board: chess.Board, color: chess.Color) -> List[chess.Square]:
    """Own pawns on the three files in front of the king, within two ranks."""
    king = board.king(color)
    if king is None:
        return []
    forward = 1 if color == chess.WHITE else -1
    king_file = chess.square_file(king)
    king_rank = chess.square_rank(king)
    shelter = []
    for file_offset in (-1, 0, 1):
        file_index = king_file + file_offset
        if not 0 <= file_index <= 7:
            continue
        for rank_offset in (1, 2):
            rank_index = king_rank + forward * rank_offset
            if not 0 <= rank_index <= 7:
                continue
            square = chess.square(file_index, rank_index)
            piece = board.piece_at(square)
            if piece is not None and piece.color == color and piece.piece_type == chess.PAWN:
                shelter.append(square)
    return shelter


def king_shelter_count(board: chess.Board, color: chess.Color) -> int:
    return len(king_shelter_squares(board, color))


def king_attacker_squares(board: chess.Board, color: chess.Color) -> List[chess.Square]:
    """Enemy pieces bearing on the squares around a king."""
    king = board.king(color)
    if king is None:
        return []
    zone = set(board.attacks(king)) | {king}
    attackers: set = set()
    for square in zone:
        attackers |= set(board.attackers(not color, square))
    return sorted(attackers)


def king_attackers(board: chess.Board, color: chess.Color) -> int:
    return len(king_attacker_squares(board, color))


def space_squares(board: chess.Board, color: chess.Color) -> List[chess.Square]:
    """Squares on the far half of the board that a side's pawns control."""
    far_ranks = range(4, 8) if color == chess.WHITE else range(0, 4)
    controlled = set()
    for square in board.pieces(chess.PAWN, color):
        for target in board.attacks(square):
            if chess.square_rank(target) in far_ranks:
                controlled.add(target)
    return sorted(controlled)


def space(board: chess.Board, color: chess.Color) -> int:
    return len(space_squares(board, color))


def undeveloped_squares(board: chess.Board, color: chess.Color) -> List[chess.Square]:
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
            idle.append(square)
    return sorted(idle)


def undeveloped(board: chess.Board, color: chess.Color) -> List[str]:
    return _names(undeveloped_squares(board, color))


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
            Concept(
                name="Material",
                detail=f"{margin:.2f} ahead",
                favours=leader,
                white_squares=_material_squares(board, chess.WHITE),
                black_squares=_material_squares(board, chess.BLACK),
            )
        )

    # Doubled pawns are named by file, the other two by square, which is how a
    # player would say them out loud.
    for label, finder, naming, weakness in (
        ("Doubled pawns", doubled_pawn_squares, doubled_pawns, True),
        ("Isolated pawns", isolated_pawn_squares, isolated_pawns, True),
        ("Passed pawns", passed_pawn_squares, passed_pawns, False),
    ):
        white = finder(board, chess.WHITE)
        black = finder(board, chess.BLACK)
        if not white and not black:
            continue
        parts = []
        if white:
            parts.append(f"White {', '.join(naming(board, chess.WHITE))}")
        if black:
            parts.append(f"Black {', '.join(naming(board, chess.BLACK))}")
        favours = None
        if bool(white) != bool(black):
            has_it = chess.WHITE if white else chess.BLACK
            favours = (not has_it) if weakness else has_it
        concepts.append(
            Concept(
                name=label,
                detail="; ".join(parts),
                favours=favours,
                white_squares=tuple(white),
                black_squares=tuple(black),
            )
        )

    white_shelter = king_shelter_squares(board, chess.WHITE)
    black_shelter = king_shelter_squares(board, chess.BLACK)
    white_pressure = king_attacker_squares(board, chess.WHITE)
    black_pressure = king_attacker_squares(board, chess.BLACK)
    if (len(white_shelter), len(white_pressure)) != (
        len(black_shelter),
        len(black_pressure),
    ):
        concepts.append(
            Concept(
                name="King safety",
                detail=(
                    f"shelter pawns {len(white_shelter)} vs {len(black_shelter)}, "
                    f"attackers on the king {len(white_pressure)} vs {len(black_pressure)}"
                ),
                favours=_favour(
                    len(white_shelter) - len(white_pressure),
                    len(black_shelter) - len(black_pressure),
                ),
                # The pawns holding each king, plus the pieces bearing on it: the
                # two halves of the count, shown together.
                white_squares=tuple(white_shelter + black_pressure),
                black_squares=tuple(black_shelter + white_pressure),
            )
        )

    white_space = space_squares(board, chess.WHITE)
    black_space = space_squares(board, chess.BLACK)
    if len(white_space) != len(black_space):
        concepts.append(
            Concept(
                name="Space",
                detail=(
                    "pawn-controlled squares in enemy territory "
                    f"{len(white_space)} vs {len(black_space)}"
                ),
                favours=_favour(len(white_space), len(black_space)),
                white_squares=tuple(white_space),
                black_squares=tuple(black_space),
            )
        )

    white_idle = undeveloped_squares(board, chess.WHITE)
    black_idle = undeveloped_squares(board, chess.BLACK)
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
                white_squares=tuple(white_idle),
                black_squares=tuple(black_idle),
            )
        )

    return concepts[:limit]


def _material_squares(board: chess.Board, color: chess.Color) -> Tuple[chess.Square, ...]:
    """A side's non-king pieces, which is what the material count adds up."""
    return tuple(
        sorted(
            square
            for square, piece in board.piece_map().items()
            if piece.color == color and piece.piece_type != chess.KING
        )
    )
