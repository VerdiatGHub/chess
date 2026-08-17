"""HTTP service for a public, unauthenticated endpoint.

Deliberately stateless. A game lives in the caller's browser and arrives as a
move list, so there are no server-side sessions to exhaust, nothing to expire,
and no way for one visitor to reach another's data. Every request is bounded by
`limits` before it reaches the engine, and the engine itself is borrowed from a
pool one request at a time.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import chess
import chess.engine
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .facts import analyse_position
from .game import load_pgn_text, moves_from_uci, review_game
from .limits import (
    CHEAP_BUCKET_CAPACITY,
    CHEAP_REFILL_PER_SECOND,
    HEAVY_BUCKET_CAPACITY,
    HEAVY_REFILL_PER_SECOND,
    MAX_BOT_MOVE_TIME,
    MAX_FEN_CHARS,
    MAX_GAME_DEPTH,
    MAX_MOVES_CHARS,
    MAX_MULTIPV,
    MAX_PGN_CHARS,
    MAX_PLIES,
    MAX_POSITION_DEPTH,
    MAX_SKILL,
    LimitExceeded,
    RateLimiter,
    check_length,
    clamp_depth,
)
from .payload import game_payload, position_payload
from .pool import EngineBusy, EnginePool

log = logging.getLogger("decodex.web")

STATIC_DIR = Path(__file__).parent / "static"

_SIDES = {
    "white": [chess.WHITE],
    "black": [chess.BLACK],
    "both": [chess.WHITE, chess.BLACK],
}


def _sides(value: str) -> List[chess.Color]:
    try:
        return _SIDES[value]
    except KeyError:
        raise LimitExceeded("side must be white, black or both")


def _board_from_fen(fen: str) -> chess.Board:
    check_length(fen, MAX_FEN_CHARS, "FEN")
    try:
        return chess.Board(fen.strip())
    except ValueError as exc:
        raise LimitExceeded(f"not a valid FEN: {exc}")


class PositionRequest(BaseModel):
    fen: str = Field(default=chess.STARTING_FEN)
    side: str = Field(default="both")
    depth: Optional[int] = None
    multipv: int = Field(default=3, ge=1)


class GameRequest(BaseModel):
    pgn: Optional[str] = None
    moves: Optional[str] = None
    side: str = Field(default="both")
    depth: Optional[int] = None


class PlayRequest(BaseModel):
    moves: List[str] = Field(default_factory=list)
    skill: int = Field(default=5, ge=0)
    moveTime: float = Field(default=0.1, gt=0)


@dataclass(frozen=True)
class RateLimits:
    """How much each tier allows. Grouped so callers can override both together."""

    heavy_capacity: float = HEAVY_BUCKET_CAPACITY
    heavy_refill: float = HEAVY_REFILL_PER_SECOND
    cheap_capacity: float = CHEAP_BUCKET_CAPACITY
    cheap_refill: float = CHEAP_REFILL_PER_SECOND


def create_app(
    engine_path: Optional[str] = None, *, rate_limits: Optional[RateLimits] = None
) -> FastAPI:
    pool: Dict[str, EnginePool] = {}
    tiers = rate_limits or RateLimits()
    # Searches and rules checks are throttled separately: one costs CPU seconds,
    # the other costs microseconds, and a shared budget would make the board
    # unusable long before the engine was under any strain.
    heavy = RateLimiter(
        capacity=tiers.heavy_capacity, refill_per_second=tiers.heavy_refill
    )
    cheap = RateLimiter(
        capacity=tiers.cheap_capacity, refill_per_second=tiers.cheap_refill
    )
    CHEAP_PATHS = {"/api/legal", "/api/limits"}

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        pool["engine"] = EnginePool(engine_path)
        log.info("engine ready at %s", pool["engine"].path)
        try:
            yield
        finally:
            pool["engine"].close()

    app = FastAPI(
        title="decodex",
        summary="Chess explanations from verifiable facts.",
        lifespan=lifespan,
    )

    def caller_of(request: Request) -> str:
        # Behind a proxy the socket address is the proxy, so prefer the first
        # forwarded hop. It is spoofable, which is acceptable: the limiter is
        # here to keep the service usable, not to establish identity.
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            limiter = cheap if path in CHEAP_PATHS else heavy
            allowed, wait = limiter.allow(caller_of(request))
            if not allowed:
                return JSONResponse(
                    {
                        "error": "Too many requests. This is a shared, free service.",
                        "retryAfterSeconds": round(wait, 1),
                    },
                    status_code=429,
                    headers={"Retry-After": str(max(1, int(wait)))},
                )
        return await call_next(request)

    @app.exception_handler(LimitExceeded)
    async def _limit_handler(_request: Request, exc: LimitExceeded):
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(EngineBusy)
    async def _busy_handler(_request: Request, exc: EngineBusy):
        return JSONResponse({"error": str(exc)}, status_code=503, headers={"Retry-After": "5"})

    @app.get("/api/limits")
    def read_limits() -> Dict[str, Any]:
        """Published so the UI can show the ceilings rather than guess them."""
        engine = pool.get("engine")
        return {
            "maxPositionDepth": MAX_POSITION_DEPTH,
            "maxGameDepth": MAX_GAME_DEPTH,
            "maxPlies": MAX_PLIES,
            "maxMultipv": MAX_MULTIPV,
            "engine": Path(engine.path).name if engine else None,
            # Lean hosts run one engine process and lose the NNUE panel, so the
            # UI can stop promising a section it will never receive.
            "lean": engine.lean if engine else False,
        }

    @app.post("/api/position")
    def post_position(body: PositionRequest) -> Dict[str, Any]:
        board = _board_from_fen(body.fen)
        colors = _sides(body.side)
        depth = clamp_depth(body.depth, MAX_POSITION_DEPTH, default=16)
        multipv = min(body.multipv, MAX_MULTIPV)

        with pool["engine"].borrow() as (search, raw):
            return {
                "depth": depth,
                "views": [
                    position_payload(
                        analyse_position(
                            board,
                            search,
                            raw,
                            perspective=color,
                            depth=depth,
                            multipv=multipv,
                        )
                    )
                    for color in colors
                ],
            }

    @app.post("/api/game")
    def post_game(body: GameRequest) -> Dict[str, Any]:
        colors = _sides(body.side)
        depth = clamp_depth(body.depth, MAX_GAME_DEPTH, default=10)

        headers: Dict[str, str] = {}
        if body.pgn:
            board, moves, headers = load_pgn_text(
                check_length(body.pgn, MAX_PGN_CHARS, "PGN")
            )
        elif body.moves:
            board = chess.Board()
            moves = _parse_moves(board, body.moves)
        else:
            raise LimitExceeded("provide either a PGN or a list of moves")

        if not moves:
            raise LimitExceeded("no moves to analyse")
        if len(moves) > MAX_PLIES:
            raise LimitExceeded(
                f"game is too long ({len(moves)} half-moves > {MAX_PLIES})"
            )

        with pool["engine"].borrow() as (search, _raw):
            review = review_game(board, moves, search, depth=depth)
        payload = game_payload(review, colors, headers)
        payload["depth"] = depth
        return payload

    @app.post("/api/legal")
    def post_legal(body: PlayRequest) -> Dict[str, Any]:
        """Board state and legal moves for a game supplied as a move list.

        The rules live here rather than in the browser, so there is one authority
        on what is legal and the UI cannot drift from it. No engine is involved,
        which makes this cheap enough to call on every click.
        """
        board = _replay(body.moves)
        return {
            "fen": board.fen(),
            "turn": "white" if board.turn == chess.WHITE else "black",
            "legal": [
                {"uci": move.uci(), "from": chess.square_name(move.from_square),
                 "to": chess.square_name(move.to_square), "san": board.san(move)}
                for move in board.legal_moves
            ],
            "over": board.is_game_over(),
            "result": board.result() if board.is_game_over() else "*",
            "status": _status_text(board),
        }

    @app.post("/api/play")
    def post_play(body: PlayRequest) -> Dict[str, Any]:
        """Reply with the bot's move for a game supplied as a move list.

        Stateless by design: the game lives in the browser, so there is no session
        for a visitor to exhaust and no cross-visitor state to leak.
        """
        board = _replay(body.moves)
        if board.is_game_over():
            return {
                "fen": board.fen(),
                "move": None,
                "over": True,
                "result": board.result(),
                "status": _status_text(board),
            }

        skill = max(0, min(body.skill, MAX_SKILL))
        move_time = min(body.moveTime, MAX_BOT_MOVE_TIME)
        with pool["engine"].borrow() as (search, _raw):
            search.configure({"Skill Level": skill})
            try:
                result = search.play(board, chess.engine.Limit(time=move_time))
            finally:
                # Leave the engine at full strength for the analysis endpoints.
                search.configure({"Skill Level": MAX_SKILL})

        if result.move is None:
            return {
                "fen": board.fen(),
                "move": None,
                "over": True,
                "result": board.result(),
                "status": _status_text(board),
            }

        san = board.san(result.move)
        board.push(result.move)
        return {
            "fen": board.fen(),
            "move": {"uci": result.move.uci(), "san": san},
            "over": board.is_game_over(),
            "result": board.result() if board.is_game_over() else "*",
            "status": _status_text(board),
        }

    @app.get("/healthz")
    def healthz() -> Dict[str, str]:
        return {"status": "ok"}

    if STATIC_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    return app


def _replay(moves: List[str]) -> chess.Board:
    """Rebuild a game from UCI moves, rejecting anything illegal."""
    if len(moves) > MAX_PLIES:
        raise LimitExceeded(f"game is too long ({len(moves)} > {MAX_PLIES})")
    board = chess.Board()
    for token in moves:
        check_length(token, 12, "move")
        try:
            board.push_uci(token)
        except ValueError:
            raise LimitExceeded(f"not a legal move in sequence: {token!r}")
    return board


def _status_text(board: chess.Board) -> str:
    if board.is_checkmate():
        return f"Checkmate — {'Black' if board.turn == chess.WHITE else 'White'} wins"
    if board.is_stalemate():
        return "Stalemate"
    if board.is_insufficient_material():
        return "Draw — insufficient material"
    if board.can_claim_fifty_moves():
        return "Draw available — fifty-move rule"
    if board.can_claim_threefold_repetition():
        return "Draw available — threefold repetition"
    side = "White" if board.turn == chess.WHITE else "Black"
    return f"{side} to move, in check" if board.is_check() else f"{side} to move"


def _parse_moves(board: chess.Board, text: str) -> List[chess.Move]:
    check_length(text, MAX_MOVES_CHARS, "move list")
    tokens = [
        token
        for token in text.replace(",", " ").split()
        # Drop PGN move numbers and result markers so a pasted game just works.
        if not token.rstrip(".").isdigit() and token not in {"1-0", "0-1", "1/2-1/2", "*"}
    ]
    try:
        return moves_from_uci(board, tokens)
    except ValueError as exc:
        raise LimitExceeded(f"could not read the moves: {exc}")
