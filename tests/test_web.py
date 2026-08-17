"""The HTTP surface, exercised end to end against a real engine."""

import chess
import pytest
from fastapi.testclient import TestClient

from decodex.limits import MAX_GAME_DEPTH, MAX_PLIES, MAX_POSITION_DEPTH
from decodex.web import RateLimits, create_app

pytestmark = pytest.mark.engine

DRAGON = "2r1k2r/1pq1ppbp/p2pbnp1/8/3BP1P1/1BN2P2/PPPQ3P/1K1R3R w k - 1 15"


@pytest.fixture(scope="module")
def client(engine_path):
    """A client with the throttle wide open, so limits do not mask real failures.

    Rate limiting is exercised in its own tests against a separate app.
    """
    generous = RateLimits(
        heavy_capacity=10_000, heavy_refill=10_000, cheap_capacity=10_000, cheap_refill=10_000
    )
    with TestClient(create_app(engine_path, rate_limits=generous)) as test_client:
        yield test_client


def test_health_and_limits_are_published(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    limits = client.get("/api/limits").json()
    assert limits["maxPositionDepth"] == MAX_POSITION_DEPTH
    assert limits["maxGameDepth"] == MAX_GAME_DEPTH
    assert limits["engine"]


def test_index_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "decodex" in response.text


def test_position_returns_facts_for_one_side(client):
    response = client.post(
        "/api/position", json={"fen": DRAGON, "side": "white", "depth": 10}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["depth"] == 10
    assert len(body["views"]) == 1

    view = body["views"][0]
    assert view["perspective"] == "White"
    assert view["evalCp"] > 0
    assert "advantage" in view["summary"]
    assert view["candidates"]
    assert view["candidates"][0]["san"]
    # The pin is board geometry, so it must be present regardless of depth.
    assert any("pinned" in line for line in view["tactics"])
    assert view["roles"]
    assert view["observations"]


def test_position_can_report_both_sides(client):
    body = client.post(
        "/api/position", json={"fen": DRAGON, "side": "both", "depth": 8}
    ).json()
    assert [view["perspective"] for view in body["views"]] == ["White", "Black"]
    # Black is not to move, so their plans come from a handed tempo.
    assert body["views"][1]["freeTempoView"] is True


def test_position_depth_is_clamped_not_rejected(client):
    body = client.post(
        "/api/position", json={"fen": DRAGON, "side": "white", "depth": 99}
    ).json()
    assert body["depth"] == MAX_POSITION_DEPTH


def test_position_rejects_a_bad_fen(client):
    response = client.post("/api/position", json={"fen": "nonsense"})
    assert response.status_code == 400
    assert "valid FEN" in response.json()["error"]


def test_position_rejects_an_oversized_fen(client):
    response = client.post("/api/position", json={"fen": "8/8/8/8/8/8/8/8 w - - 0 1" + "x" * 500})
    assert response.status_code == 400
    assert "too long" in response.json()["error"]


def test_position_rejects_an_unknown_side(client):
    response = client.post("/api/position", json={"fen": DRAGON, "side": "green"})
    assert response.status_code == 400


def test_game_review_from_a_move_list(client):
    body = client.post(
        "/api/game",
        json={"moves": "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0", "depth": 8},
    ).json()
    assert body["result"] == "1-0"
    assert len(body["moves"]) == 7
    assert len(body["graph"]) == 7

    black = next(side for side in body["sides"] if side["side"] == "Black")
    blunder = next(m for m in black["turningPoints"] if m["san"] == "Nf6")
    assert blunder["verdict"] == "blunder"
    assert blunder["allowedMate"] is True


def test_game_review_from_a_pgn(client):
    pgn = (
        '[Event "t"]\n[White "alice"]\n[Black "bob"]\n[Result "1-0"]\n\n'
        "1. e4 e5 2. Bc4 Nc6 3. Qh5 Nf6 4. Qxf7# 1-0\n"
    )
    body = client.post("/api/game", json={"pgn": pgn, "depth": 8}).json()
    assert body["white"] == "alice"
    assert body["black"] == "bob"
    assert body["result"] == "1-0"


def test_game_review_can_be_scoped_to_one_side(client):
    body = client.post(
        "/api/game", json={"moves": "e4 e5 Nf3 Nc6", "side": "white", "depth": 8}
    ).json()
    assert [side["side"] for side in body["sides"]] == ["White"]


def test_game_needs_something_to_analyse(client):
    assert client.post("/api/game", json={}).status_code == 400
    assert client.post("/api/game", json={"moves": "   "}).status_code == 400


def test_game_rejects_an_unreadable_move(client):
    response = client.post("/api/game", json={"moves": "e4 e5 Zz9"})
    assert response.status_code == 400
    assert "could not read" in response.json()["error"]


def test_game_rejects_an_overlong_game(client):
    # Legal but far past the ply ceiling, so it must be refused on length.
    moves = " ".join(["Nf3 Nf6 Ng1 Ng8"] * 60)
    response = client.post("/api/game", json={"moves": moves})
    assert response.status_code == 400
    assert str(MAX_PLIES) in response.json()["error"]


def test_legal_moves_come_from_the_server(client):
    body = client.post("/api/legal", json={"moves": []}).json()
    assert body["turn"] == "white"
    assert len(body["legal"]) == 20
    assert {"uci": "e2e4", "from": "e2", "to": "e4", "san": "e4"} in body["legal"]
    assert body["over"] is False


def test_legal_moves_track_the_game(client):
    body = client.post("/api/legal", json={"moves": ["e2e4", "e7e5"]}).json()
    assert body["turn"] == "white"
    assert body["status"] == "White to move"


def test_legal_reports_a_finished_game(client):
    mate = ["f2f3", "e7e5", "g2g4", "d8h4"]
    body = client.post("/api/legal", json={"moves": mate}).json()
    assert body["over"] is True
    assert body["result"] == "0-1"
    assert "Checkmate" in body["status"]


def test_illegal_move_sequences_are_refused(client):
    response = client.post("/api/legal", json={"moves": ["e2e4", "e2e4"]})
    assert response.status_code == 400
    assert "not a legal move" in response.json()["error"]


def test_play_answers_with_a_legal_move(client):
    body = client.post(
        "/api/play", json={"moves": ["e2e4"], "skill": 1, "moveTime": 0.05}
    ).json()
    assert body["move"] is not None
    board = chess.Board()
    board.push_uci("e2e4")
    assert chess.Move.from_uci(body["move"]["uci"]) in board.legal_moves
    assert body["over"] is False


def test_play_on_a_finished_game_returns_no_move(client):
    mate = ["f2f3", "e7e5", "g2g4", "d8h4"]
    body = client.post("/api/play", json={"moves": mate}).json()
    assert body["move"] is None
    assert body["over"] is True


def test_play_leaves_the_engine_at_full_strength(client):
    """Skill Level is global to the engine process, so it must be restored.

    Without this the first weak bot move would silently cripple every later
    analysis request for everyone sharing the service.
    """
    client.post("/api/play", json={"moves": ["e2e4"], "skill": 0, "moveTime": 0.05})
    body = client.post(
        "/api/position",
        json={"fen": "4k3/8/8/8/8/8/4r3/4K3 b - - 0 1", "side": "black", "depth": 8},
    ).json()
    # Black is up a rook; a hobbled engine would not report that cleanly.
    assert body["views"][0]["evalCp"] < -300


def test_rate_limit_eventually_refuses_heavy_calls(engine_path):
    # A separate app, so this cannot exhaust the shared client's budget.
    with TestClient(create_app(engine_path)) as client:
        codes = set()
        for _ in range(20):
            codes.add(
                client.post(
                    "/api/position",
                    json={"fen": "4k3/8/8/8/8/8/8/4K3 w - - 0 1", "depth": 6, "side": "white"},
                ).status_code
            )
        assert 429 in codes


def test_cheap_calls_are_not_throttled_like_searches(engine_path):
    # Clicking around the board must not spend the analysis budget.
    with TestClient(create_app(engine_path)) as client:
        codes = {
            client.post("/api/legal", json={"moves": []}).status_code
            for _ in range(30)
        }
        assert codes == {200}


def test_lean_mode_serves_every_fact_except_the_nnue_panel(engine_path, monkeypatch):
    """A 512 MB host cannot afford two engine processes.

    Only the NNUE piece-importance table needs the second one, so lean mode has
    to drop that panel and keep everything else working rather than fail.
    """
    monkeypatch.setenv("DECODEX_LEAN", "1")
    generous = RateLimits(
        heavy_capacity=10_000, heavy_refill=10_000, cheap_capacity=10_000, cheap_refill=10_000
    )
    with TestClient(create_app(engine_path, rate_limits=generous)) as client:
        assert client.get("/api/limits").json()["lean"] is True

        view = client.post(
            "/api/position", json={"fen": DRAGON, "side": "white", "depth": 10}
        ).json()["views"][0]

        # The one casualty.
        assert view["contributions"] == []
        # Everything else still arrives, including an evaluation, which now comes
        # from the best line rather than from the eval trace.
        assert view["evalCp"] is not None
        assert "advantage" in view["summary"]
        assert view["candidates"]
        assert any("pinned" in line for line in view["tactics"])
        assert view["roles"]
        assert view["concepts"]
        assert view["observations"]
        assert view["threatBefore"]

        # And a game review, which never used the eval trace, is unaffected.
        game = client.post(
            "/api/game", json={"moves": "e4 e5 Bc4 Nc6 Qh5 Nf6 Qxf7#", "depth": 8}
        ).json()
        assert game["result"] == "1-0"


def test_lean_mode_is_off_by_default(engine_path):
    with TestClient(create_app(engine_path)) as client:
        assert client.get("/api/limits").json()["lean"] is False
