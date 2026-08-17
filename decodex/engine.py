"""Stockfish access: search via UCI plus raw `eval` traces.

Two channels are used because python-chess deliberately exposes only the
standard UCI surface, and the per-piece ablation table we need comes from
Stockfish's non-standard `eval` command.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional

import chess

ENGINE_ENV_VAR = "DECODEX_ENGINE"
_CANDIDATE_NAMES = ("stockfish", "stockfish17", "stockfish16")
_READ_TIMEOUT = 30.0


class EngineNotFound(RuntimeError):
    pass


def find_engine(path: Optional[str] = None) -> str:
    for candidate in (path, os.environ.get(ENGINE_ENV_VAR), *_CANDIDATE_NAMES):
        if not candidate:
            continue
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    raise EngineNotFound(
        "No UCI engine found. Install Stockfish, or pass --engine, "
        f"or set {ENGINE_ENV_VAR}."
    )


@dataclass(frozen=True)
class PieceValue:
    """One cell of Stockfish's NNUE derived piece values table.

    `value` is in pawns and signed from white's point of view, so a piece's
    importance to its own side is `abs(value)`. Kings have no value because
    they cannot be removed from the board.
    """

    square: str
    symbol: str
    value: Optional[float]

    @property
    def color(self) -> chess.Color:
        return chess.WHITE if self.symbol.isupper() else chess.BLACK

    @property
    def magnitude(self) -> float:
        return abs(self.value) if self.value is not None else 0.0


@dataclass(frozen=True)
class EvalTrace:
    final_cp: Optional[int]
    piece_values: Dict[str, PieceValue] = field(default_factory=dict)
    in_check: bool = False

    def for_color(self, color: chess.Color) -> list[PieceValue]:
        return sorted(
            (
                p
                for p in self.piece_values.values()
                if p.color == color and p.value is not None
            ),
            key=lambda p: p.magnitude,
            reverse=True,
        )


_FINAL_EVAL_RE = re.compile(r"Final evaluation\s+([+-]?\d+\.\d+)")


def parse_eval_trace(text: str) -> EvalTrace:
    if "Final evaluation: none (in check)" in text:
        return EvalTrace(final_cp=None, in_check=True)

    lines = text.splitlines()
    table_start = next(
        (i + 1 for i, line in enumerate(lines) if "NNUE derived piece values" in line),
        None,
    )

    piece_values: Dict[str, PieceValue] = {}
    if table_start is not None:
        rows: list[list[str]] = []
        for line in lines[table_start:]:
            stripped = line.strip()
            if stripped.startswith("+--"):
                continue
            if not stripped.startswith("|"):
                break
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if len(cells) != 8:
                break
            rows.append(cells)
            if len(rows) == 16:
                break

        # Rows alternate: piece symbols, then that rank's values, from rank 8 down.
        for index in range(0, len(rows) - 1, 2):
            rank = 8 - index // 2
            for file_index, (symbol, raw) in enumerate(
                zip(rows[index], rows[index + 1])
            ):
                if not symbol:
                    continue
                square = chess.square_name(chess.square(file_index, rank - 1))
                piece_values[square] = PieceValue(
                    square=square,
                    symbol=symbol,
                    value=float(raw) if raw else None,
                )

    match = _FINAL_EVAL_RE.search(text)
    final_cp = int(round(float(match.group(1)) * 100)) if match else None
    return EvalTrace(final_cp=final_cp, piece_values=piece_values)


class RawEngine:
    """A long-lived engine process used only for `eval` traces.

    Kept separate from the search engine so the NNUE network is loaded once
    rather than per position.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._proc = subprocess.Popen(
            [path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._send("uci")
        self._read_until("uciok")

    def _send(self, command: str) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(command + "\n")
        self._proc.stdin.flush()

    def _read_until(self, sentinel: str) -> str:
        """Read lines until one starts with `sentinel`.

        Blocking reads are used deliberately: `select` on the pipe is unusable
        here because the buffered reader pulls several lines in at once, leaving
        the sentinel in Python's buffer while the file descriptor looks idle. A
        watchdog kills the process instead, so a wedged engine still fails.
        """
        assert self._proc.stdout is not None
        watchdog = threading.Timer(_READ_TIMEOUT, self._proc.kill)
        watchdog.start()
        collected: list[str] = []
        try:
            while True:
                line = self._proc.stdout.readline()
                if not line:
                    raise RuntimeError(
                        f"engine stopped responding before {sentinel!r}"
                    )
                if line.startswith(sentinel):
                    return "".join(collected)
                collected.append(line)
        finally:
            watchdog.cancel()

    def eval_trace(self, board: chess.Board) -> EvalTrace:
        self._send(f"position fen {board.fen()}")
        self._send("eval")
        self._send("isready")
        return parse_eval_trace(self._read_until("readyok"))

    def close(self) -> None:
        if self._proc.poll() is None:
            try:
                self._send("quit")
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()

    def __enter__(self) -> "RawEngine":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
