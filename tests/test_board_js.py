"""Board geometry in the browser client, checked against python-chess.

Square colour and FEN expansion are the kind of arithmetic that looks right in a
screenshot and is wrong. The first version of the UI had the parity inverted, so
these run the real JS under node and compare every square against python-chess
rather than trusting a visual check.
"""

import json
import shutil
import subprocess
from pathlib import Path

import chess
import pytest

BOARD_JS = Path(__file__).parent.parent / "decodex" / "static" / "board.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node is needed to run the browser code"
)


def run_js(script: str):
    """Execute a snippet with board.js loaded, and parse what it prints."""
    program = f"const B = require({str(BOARD_JS)!r});\n{script}"
    result = subprocess.run(
        ["node", "-e", program], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_every_square_colour_matches_python_chess():
    colours = run_js(
        """
        const out = {};
        for (let f = 0; f < 8; f += 1) {
          for (let r = 1; r <= 8; r += 1) {
            out[B.FILES[f] + r] = B.isLightSquare(f, r);
          }
        }
        console.log(JSON.stringify(out));
        """
    )
    assert len(colours) == 64
    for name, is_light in colours.items():
        square = chess.parse_square(name)
        expected = bool(chess.BB_LIGHT_SQUARES & chess.BB_SQUARES[square])
        assert is_light == expected, f"{name} should be {'light' if expected else 'dark'}"


def test_the_corners_are_the_way_round_everyone_recognises():
    corners = run_js(
        """
        console.log(JSON.stringify({
          a1: B.isLightSquare(0, 1),
          h1: B.isLightSquare(7, 1),
          a8: B.isLightSquare(0, 8),
          h8: B.isLightSquare(7, 8),
        }));
        """
    )
    # A player looking at the board knows a1 is dark and h1 is light.
    assert corners == {"a1": False, "h1": True, "a8": True, "h8": False}


def test_fen_expands_to_the_same_pieces_python_chess_sees():
    fen = "2r1k2r/1pq1ppbp/p2pbnp1/8/3BP1P1/1BN2P2/PPPQ3P/1K1R3R w k - 1 15"
    grid = run_js(f"console.log(JSON.stringify(B.expandFen({fen!r})));")
    assert len(grid) == 8
    assert all(len(row) == 8 for row in grid)

    board = chess.Board(fen)
    for row_index, row in enumerate(grid):
        rank = 8 - row_index
        for file_index, symbol in enumerate(row):
            piece = board.piece_at(chess.square(file_index, rank - 1))
            assert symbol == (piece.symbol() if piece else None)


def test_the_starting_position_expands_correctly():
    grid = run_js(
        "console.log(JSON.stringify(B.expandFen("
        "'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1')));"
    )
    assert grid[0] == list("rnbqkbnr")
    assert grid[1] == list("pppppppp")
    assert grid[2] == [None] * 8
    assert grid[7] == list("RNBQKBNR")


def test_an_empty_board_expands_to_all_gaps():
    grid = run_js("console.log(JSON.stringify(B.expandFen('8/8/8/8/8/8/8/8 w - - 0 1')));")
    assert grid == [[None] * 8 for _ in range(8)]


@pytest.mark.parametrize(
    "fen",
    [
        "",
        "nonsense",
        "8/8/8/8/8/8/8",  # seven ranks
        "8/8/8/8/8/8/8/8/8",  # nine ranks
        "9/8/8/8/8/8/8/8",  # a rank of nine
        "7/8/8/8/8/8/8/8",  # a rank of seven
        "xxxxxxxx/8/8/8/8/8/8/8",  # not piece letters
    ],
)
def test_a_malformed_fen_is_refused_rather_than_half_drawn(fen):
    assert run_js(f"console.log(JSON.stringify(B.expandFen({fen!r})));") is None


def test_board_order_draws_64_squares_once_each():
    for flipped in ("false", "true"):
        cells = run_js(f"console.log(JSON.stringify(B.boardOrder({flipped})));")
        assert len(cells) == 64
        assert len({cell["square"] for cell in cells}) == 64


def test_white_reads_top_left_to_bottom_right():
    cells = run_js("console.log(JSON.stringify(B.boardOrder(false)));")
    assert cells[0]["square"] == "a8"
    assert cells[7]["square"] == "h8"
    assert cells[56]["square"] == "a1"
    assert cells[63]["square"] == "h1"


def test_black_sees_the_exact_reverse():
    white = run_js("console.log(JSON.stringify(B.boardOrder(false)));")
    black = run_js("console.log(JSON.stringify(B.boardOrder(true)));")
    assert [c["square"] for c in black] == [c["square"] for c in white][::-1]


def test_square_colour_does_not_change_when_the_board_flips():
    white = {c["square"]: c["light"] for c in run_js(
        "console.log(JSON.stringify(B.boardOrder(false)));")}
    black = {c["square"]: c["light"] for c in run_js(
        "console.log(JSON.stringify(B.boardOrder(true)));")}
    # Turning the board round does not repaint it.
    assert white == black


def test_coordinates_sit_on_the_near_and_bottom_edges():
    for flipped, home_rank, near_file in ((False, 1, "a"), (True, 8, "h")):
        cells = run_js(
            f"console.log(JSON.stringify(B.boardOrder({str(flipped).lower()})));"
        )
        files = {c["square"] for c in cells if c["showFile"]}
        ranks = {c["square"] for c in cells if c["showRank"]}
        assert files == {f"{f}{home_rank}" for f in "abcdefgh"}
        assert ranks == {f"{near_file}{r}" for r in range(1, 9)}
