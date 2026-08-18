"""Command line entry point."""

from __future__ import annotations

import argparse
import sys
from contextlib import contextmanager
from typing import Iterator, List, Optional

import chess
import chess.engine

from .concepts import describe_concepts
from .engine import RawEngine, find_engine
from .facts import analyse_position
from .game import GameReview, load_pgn, moves_from_uci, review_game
from .motifs import tactic_insights
from .play import PlaySession
from .report import render_game, render_position, side_name
from .roles import describe_roles

SIDE_CHOICES = ("white", "black", "both")


def parse_sides(value: str) -> List[Optional[chess.Color]]:
    if value == "white":
        return [chess.WHITE]
    if value == "black":
        return [chess.BLACK]
    return [chess.WHITE, chess.BLACK]


@contextmanager
def engines(path: str, threads: int, hash_mb: int) -> Iterator[tuple]:
    search = chess.engine.SimpleEngine.popen_uci(path)
    search.configure({"Threads": threads, "Hash": hash_mb})
    raw = RawEngine(path)
    try:
        yield search, raw
    finally:
        raw.close()
        search.quit()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="decodex",
        description="Explain engine moves from ground-truth facts, not guesses.",
    )
    parser.add_argument("--engine", help="path to a UCI engine (default: stockfish)")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--hash", type=int, default=256, dest="hash_mb")
    sub = parser.add_subparsers(dest="command", required=True)

    position = sub.add_parser("position", help="analyse a single position")
    position.add_argument("--fen", default=chess.STARTING_FEN)
    position.add_argument("--side", choices=SIDE_CHOICES, default="both")
    position.add_argument("--depth", type=int, default=18)
    position.add_argument("--multipv", type=int, default=3)

    game = sub.add_parser("game", help="analyse a whole game")
    source = game.add_mutually_exclusive_group(required=True)
    source.add_argument("--pgn", help="path to a PGN file")
    source.add_argument("--moves", help="space separated SAN or UCI moves")
    game.add_argument("--side", choices=SIDE_CHOICES, default="both")
    game.add_argument("--depth", type=int, default=14)
    game.add_argument("--all-moves", action="store_true", help="list every move")

    play = sub.add_parser("play", help="play the bot, decode as you go")
    play.add_argument("--color", choices=("white", "black"), default="white")
    play.add_argument("--skill", type=int, default=5, help="engine skill 0-20")
    play.add_argument("--move-time", type=float, default=0.1)
    play.add_argument("--depth", type=int, default=16)
    return parser


def cmd_position(args: argparse.Namespace, search, raw) -> int:
    board = chess.Board(args.fen)
    for color in parse_sides(args.side):
        facts = analyse_position(
            board,
            search,
            raw,
            perspective=color,
            depth=args.depth,
            multipv=args.multipv,
        )
        print(render_position(facts))
        print()
    return 0


def _load_moves(args: argparse.Namespace) -> tuple[chess.Board, list, dict]:
    if args.pgn:
        return load_pgn(args.pgn)
    board = chess.Board()
    return board, moves_from_uci(board, args.moves.split()), {}


def cmd_game(args: argparse.Namespace, search, raw) -> int:
    board, moves, headers = _load_moves(args)
    if not moves:
        print("No moves to analyse.", file=sys.stderr)
        return 1

    def progress(done: int, total: int) -> None:
        print(f"\ranalysing {done}/{total} plies", end="", file=sys.stderr)

    review = review_game(board, moves, search, depth=args.depth, progress=progress)
    print("\r" + " " * 32 + "\r", end="", file=sys.stderr)
    print(
        render_game(
            review, parse_sides(args.side), headers, verbose=args.all_moves
        )
    )
    return 0


_PLAY_HELP = """
Commands
  <move>              play a move (SAN like Nf3, or UCI like g1f3)
  decode [side]       analyse the current position (white/black/both)
  review [side]       analyse the game so far
  roles [side]        what each piece is doing
  concepts            structural features of the position
  tactics             pins, skewers, batteries, forks, discovered attacks
  board               redraw the board
  pgn                 print the game as PGN
  undo                take back your move and the bot's reply
  help                show this
  quit                leave
""".strip()


def _decode_now(session: PlaySession, search, raw, depth: int, side: str) -> None:
    for color in parse_sides(side):
        facts = analyse_position(
            session.board, search, raw, perspective=color, depth=depth
        )
        print(render_position(facts))
        print()


def _roles_now(session: PlaySession, side: str) -> None:
    for color in parse_sides(side):
        print(f"Piece roles for {side_name(color)}")
        for role in describe_roles(session.board, color):
            print(f"  - {role.describe()}")
        print()


def _concepts_now(session: PlaySession) -> None:
    concepts = describe_concepts(session.board)
    if not concepts:
        print("Nothing structural separates the two sides.")
        return
    print("Concepts")
    for concept in concepts:
        print(f"  {concept.describe()}")
    print()


def _tactics_now(session: PlaySession) -> None:
    items = tactic_insights(session.board)
    if not items:
        print("No tactical motifs on the board.")
        return
    print("Tactics on the board")
    for item in items:
        print(f"  - {item.text}")
    print()


def _review_now(session: PlaySession, search, depth: int, side: str) -> None:
    if not session.moves:
        print("No moves played yet.")
        return
    review: GameReview = review_game(
        chess.Board(), session.moves, search, depth=max(8, depth - 4)
    )
    print(render_game(review, parse_sides(side)))
    print()


def cmd_play(args: argparse.Namespace, search, raw) -> int:
    human = chess.WHITE if args.color == "white" else chess.BLACK
    session = PlaySession(
        bot_color=not human, skill=args.skill, move_time=args.move_time
    )
    print(f"You are {side_name(human)}. Bot skill {args.skill}.")
    print(_PLAY_HELP)
    print()
    print(session.render_board())

    while True:
        if session.bot_to_move:
            move = session.bot_move(search)
            if move is not None:
                print(f"\nBot plays {move.uci()}")
                print(session.render_board())
                print(session.status())
            continue

        if session.board.is_game_over():
            print(session.status())
            return 0

        try:
            raw_input_text = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not raw_input_text:
            continue

        parts = raw_input_text.split()
        command, rest = parts[0].lower(), parts[1:]

        if command in ("quit", "exit"):
            return 0
        if command == "help":
            print(_PLAY_HELP)
            continue
        if command == "board":
            print(session.render_board())
            print(session.status())
            continue
        if command == "pgn":
            print(session.to_pgn())
            continue
        if command == "undo":
            session.undo(2)
            print(session.render_board())
            continue
        if command == "decode":
            side = rest[0] if rest and rest[0] in SIDE_CHOICES else "both"
            _decode_now(session, search, raw, args.depth, side)
            continue
        if command == "review":
            side = rest[0] if rest and rest[0] in SIDE_CHOICES else "both"
            _review_now(session, search, args.depth, side)
            continue
        if command == "roles":
            side = rest[0] if rest and rest[0] in SIDE_CHOICES else "both"
            _roles_now(session, side)
            continue
        if command == "concepts":
            _concepts_now(session)
            continue
        if command == "tactics":
            _tactics_now(session)
            continue

        try:
            session.push_san_or_uci(raw_input_text)
        except ValueError:
            print(f"Not a legal move or known command: {raw_input_text!r}")
            continue
        print(session.render_board())
        print(session.status())


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    path = find_engine(args.engine)
    handlers = {"position": cmd_position, "game": cmd_game, "play": cmd_play}
    with engines(path, args.threads, args.hash_mb) as (search, raw):
        return handlers[args.command](args, search, raw)


if __name__ == "__main__":
    raise SystemExit(main())
