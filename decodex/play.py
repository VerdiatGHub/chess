"""Play against the engine, and analyse without leaving the game.

Mirrors the DecodeChess loop: while a game is in progress you can decode the
current position or the game so far, for either side or both.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import chess
import chess.engine
import chess.pgn


@dataclass
class PlaySession:
    """A game in progress against the engine.

    Skill is Stockfish's own `Skill Level` option (0-20); move time keeps the
    bot responsive rather than strong.
    """

    bot_color: chess.Color
    skill: int = 5
    move_time: float = 0.1
    board: chess.Board = field(default_factory=chess.Board)
    moves: List[chess.Move] = field(default_factory=list)

    @property
    def human_color(self) -> chess.Color:
        return not self.bot_color

    @property
    def bot_to_move(self) -> bool:
        return self.board.turn == self.bot_color and not self.board.is_game_over()

    def push_san_or_uci(self, text: str) -> chess.Move:
        try:
            move = self.board.parse_san(text)
        except ValueError:
            move = self.board.parse_uci(text)
        self.board.push(move)
        self.moves.append(move)
        return move

    def push(self, move: chess.Move) -> None:
        self.board.push(move)
        self.moves.append(move)

    def bot_move(self, engine: chess.engine.SimpleEngine) -> Optional[chess.Move]:
        if not self.bot_to_move:
            return None
        engine.configure({"Skill Level": self.skill})
        result = engine.play(self.board, chess.engine.Limit(time=self.move_time))
        if result.move is None:
            return None
        self.push(result.move)
        return result.move

    def undo(self, count: int = 1) -> None:
        for _ in range(min(count, len(self.moves))):
            self.board.pop()
            self.moves.pop()

    def to_pgn(self, headers: Optional[dict] = None) -> str:
        game = chess.pgn.Game()
        supplied = headers or {}
        # chess.pgn.Game ships placeholder "?" headers, so setdefault would
        # never fill these in.
        game.headers["White"] = supplied.get(
            "White", "Bot" if self.bot_color == chess.WHITE else "Human"
        )
        game.headers["Black"] = supplied.get(
            "Black", "Bot" if self.bot_color == chess.BLACK else "Human"
        )
        for key, value in supplied.items():
            game.headers[key] = value
        node: chess.pgn.GameNode = game
        for move in self.moves:
            node = node.add_variation(move)
        game.headers["Result"] = (
            self.board.result() if self.board.is_game_over() else "*"
        )
        return str(game)

    def status(self) -> str:
        if self.board.is_checkmate():
            winner = "Black" if self.board.turn == chess.WHITE else "White"
            return f"Checkmate — {winner} wins"
        if self.board.is_stalemate():
            return "Stalemate"
        if self.board.is_insufficient_material():
            return "Draw — insufficient material"
        if self.board.can_claim_fifty_moves():
            return "Draw available — fifty-move rule"
        if self.board.can_claim_threefold_repetition():
            return "Draw available — threefold repetition"
        if self.board.is_check():
            return f"{'White' if self.board.turn == chess.WHITE else 'Black'} to move, in check"
        return f"{'White' if self.board.turn == chess.WHITE else 'Black'} to move"

    def render_board(self) -> str:
        return self.board.unicode(borders=True, empty_square=".")
