"""Geometry attached to facts: no engine required.

The point of a cue is that the drawing and the sentence come from the same
detector. These tests check that link rather than the wording, which the other
static tests already cover: every square a cue names must be one the position
actually holds, and the tone must match what the sentence claims.
"""

import chess

from decodex.concepts import describe_concepts
from decodex.cues import (
    ARROW_TONES,
    MARK_TONES,
    Cue,
    Insight,
    arrow,
    between,
    cue,
    move_arrow,
    move_cue,
    square_name,
)
from decodex.motifs import (
    find_alignments,
    find_batteries,
    find_discovered_attacks,
    find_forks,
    relation_insights,
    tactic_insights,
)
from decodex.plans import explain_move
from decodex.roles import describe_roles

DRAGON = "2r1k2r/1pq1ppbp/p2pbnp1/8/3BP1P1/1BN2P2/PPPQ3P/1K1R3R w k - 1 15"


def squares_of(item: Cue) -> set:
    """Every square a cue refers to, from marks and both ends of each arrow."""
    named = {mark.square for mark in item.marks}
    for line in item.arrows:
        named.add(line.origin)
        named.add(line.target)
    return named


# ---------------- the primitives ----------------


def test_a_square_can_be_given_as_an_index_or_a_name():
    assert square_name(chess.E4) == "e4"
    assert square_name("e4") == "e4"


def test_a_square_that_does_not_exist_is_refused():
    for bad in ("", "e9", "j4", "E4", "e"):
        try:
            square_name(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should not be accepted as a square")


def test_only_the_agreed_tones_are_accepted():
    assert set(MARK_TONES) == {"actor", "target", "friend", "zone"}
    for tone in ARROW_TONES:
        assert arrow("e2", "e4", tone).tone == tone
    for bad in ("attack ", "highlight", ""):
        try:
            arrow("e2", "e4", bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should not be an arrow tone")


def test_the_keyword_names_are_the_tones_they_produce():
    item = cue(actors=["a1"], targets=["b1"], friends=["c1"], zone=["d1"])
    assert {mark.square: mark.tone for mark in item.marks} == {
        "a1": "actor",
        "b1": "target",
        "c1": "friend",
        "d1": "zone",
    }


def test_an_arrow_needs_two_different_squares():
    try:
        arrow("e4", "e4", "move")
    except ValueError:
        return
    raise AssertionError("an arrow from a square to itself is not drawable")


def test_the_first_tone_given_to_a_square_wins():
    # Detectors pass the most specific role first, so a square that is both the
    # actor and part of the zone is drawn as the actor.
    item = cue(actors=["e4"], zone=["e4", "e5"])
    tones = {mark.square: mark.tone for mark in item.marks}
    assert tones == {"e4": "actor", "e5": "zone"}


def test_a_repeated_arrow_is_drawn_once():
    item = cue(arrows=[arrow("a1", "a8", "attack"), arrow("a1", "a8", "attack")])
    assert len(item.arrows) == 1


def test_an_empty_cue_is_falsey_so_the_ui_can_skip_it():
    assert not cue()
    assert cue(actors=["e4"])


def test_merging_keeps_both_claims():
    merged = cue(actors=["e2"]).merge(cue(targets=["e4"]))
    assert squares_of(merged) == {"e2", "e4"}


def test_a_move_is_drawn_from_where_it_starts_to_where_it_lands():
    move = chess.Move.from_uci("g1f3")
    assert move_arrow(move).origin == "g1"
    assert move_arrow(move).target == "f3"

    item = move_cue(move)
    tones = {mark.square: mark.tone for mark in item.marks}
    assert tones == {"g1": "actor", "f3": "zone"}
    assert [line.tone for line in item.arrows] == ["move"]


def test_between_lists_the_squares_a_slider_crosses():
    assert between("a1", "a4") == ["a2", "a3"]
    assert between(chess.A1, chess.D4) == ["b2", "c3"]
    # Adjacent squares have nothing in between, and nor do unrelated ones.
    assert between("a1", "a2") == []
    assert between("a1", "b4") == []


def test_an_insight_carries_no_geometry_unless_it_is_given_some():
    assert not Insight("something true").cue


# ---------------- geometry that matches the position ----------------


def test_every_square_a_tactic_names_holds_a_piece_or_lies_on_its_line():
    board = chess.Board(DRAGON)
    occupied = {chess.square_name(square) for square in board.piece_map()}
    for item in tactic_insights(board):
        assert item.cue, f"{item.text} was reported without geometry"
        for mark in item.cue.marks:
            if mark.tone == "zone":
                continue  # A crossed square is empty by definition.
            assert mark.square in occupied, f"{item.text} points at empty {mark.square}"


def test_a_pin_lights_the_attacker_the_victim_and_the_line():
    # White bishop d4 looks through f6 to the bishop on g7: the knight is pinned.
    board = chess.Board(DRAGON)
    pin = next(
        item
        for item in find_alignments(board)
        if item.kind == "pin" and chess.square_name(item.near) == "f6"
    )
    item = pin.cue()
    tones = {mark.square: mark.tone for mark in item.marks}
    assert tones["d4"] == "actor"
    assert tones["f6"] == "target"
    assert tones["g7"] == "target"
    # e5 is the empty square the bishop looks through.
    assert tones["e5"] == "zone"
    assert [(line.origin, line.target, line.tone) for line in item.arrows] == [
        ("d4", "g7", "attack")
    ]


def test_a_skewer_is_drawn_the_same_way_round_as_it_is_described():
    # The rook on a1 hits the queen on a4 with the rook on a8 behind it.
    board = chess.Board("r3k3/8/8/8/q7/8/8/R3K3 w - - 0 1")
    skewer = next(item for item in find_alignments(board) if item.kind == "skewer")
    squares = squares_of(skewer.cue())
    assert chess.square_name(skewer.attacker) in squares
    assert chess.square_name(skewer.near) in squares
    assert chess.square_name(skewer.far) in squares


def test_a_battery_aimed_at_something_draws_an_attack_not_a_defence():
    # Rooks doubled on the d-file, a black knight at the end of it.
    board = chess.Board("3nk3/8/8/8/8/8/3R4/3RK3 w - - 0 1")
    battery = next(item for item in find_batteries(board) if item.target is not None)
    tones = [line.tone for line in battery.cue().arrows]
    assert tones == ["attack"]


def test_a_battery_with_nothing_in_front_of_it_draws_support():
    board = chess.Board("4k3/8/8/8/8/8/3R4/3RK3 w - - 0 1")
    battery = next(item for item in find_batteries(board) if item.target is None)
    assert [line.tone for line in battery.cue().arrows] == ["support"]


def test_a_fork_points_at_every_piece_it_hits():
    # Nd5+ hits the king on e7 and the rook on c7 at once.
    board = chess.Board("8/2r1k3/8/8/1N6/8/8/4K3 w - - 0 1")
    fork = find_forks(board)[0]
    item = fork.cue()
    squares = squares_of(item)
    for square in fork.target_squares:
        assert chess.square_name(square) in squares
    # The move first, then one arrow per piece hit from where it lands.
    assert [line.tone for line in item.arrows] == ["move", "attack", "attack"]


def test_a_discovered_attack_draws_the_piece_that_moves_and_the_line_it_opens():
    board = chess.Board("q3k3/8/8/8/N7/8/8/R3K3 w - - 0 1")
    found = next(iter(find_discovered_attacks(board)))
    item = found.cue()
    squares = squares_of(item)
    # The knight steps aside; the rook behind it does the work.
    assert "a4" in squares
    assert "a1" in squares
    assert "a8" in squares


def test_a_relation_draws_an_attack_towards_the_piece_being_attacked():
    board = chess.Board(DRAGON)
    capture = next(
        item for item in relation_insights(board) if "can capture" in item.text
    )
    assert [line.tone for line in capture.cue.arrows] == ["attack"]
    origin, target = capture.cue.arrows[0].origin, capture.cue.arrows[0].target
    # The sentence names the pieces in the same order the arrow is drawn.
    assert capture.text.index(origin) < capture.text.index(target)


def test_a_defence_is_drawn_as_support_and_marks_the_piece_as_a_friend():
    board = chess.Board(DRAGON)
    support = next(item for item in relation_insights(board) if "supports" in item.text)
    assert [line.tone for line in support.cue.arrows] == ["support"]
    assert any(mark.tone == "friend" for mark in support.cue.marks)


def test_a_role_lights_the_piece_it_is_about():
    board = chess.Board(DRAGON)
    for role in describe_roles(board, chess.WHITE):
        marks = {mark.square: mark.tone for mark in role.cue().marks}
        assert marks[chess.square_name(role.square)] == "actor"


def test_a_concept_shows_the_squares_its_number_was_counted_from():
    board = chess.Board(DRAGON)
    for concept in describe_concepts(board):
        # A concept about the whole position may have nothing to point at, but
        # anything it does point at has to be a real square.
        for mark in concept.cue().marks:
            assert mark.square in chess.SQUARE_NAMES


def test_a_purpose_draws_the_move_it_explains():
    board = chess.Board(DRAGON)
    pv = []
    walker = board.copy()
    for san in ("h4", "Rg8", "h5"):
        move = walker.parse_san(san)
        pv.append(move)
        walker.push(move)

    purposes = explain_move(board, pv)
    assert purposes
    for purpose in purposes:
        tones = {mark.square: mark.tone for mark in purpose.cue.marks}
        assert tones["h2"] == "actor"
        assert "h4" in tones
        assert any(line.tone == "move" for line in purpose.cue.arrows)


def test_the_follow_up_draws_both_hops_of_the_plan():
    board = chess.Board(DRAGON)
    pv = []
    walker = board.copy()
    for san in ("h4", "Rg8", "h5"):
        move = walker.parse_san(san)
        pv.append(move)
        walker.push(move)

    follow_up = next(p for p in explain_move(board, pv) if p.kind == "follow_up")
    drawn = [(line.origin, line.target, line.tone) for line in follow_up.cue.arrows]
    assert ("h2", "h4", "move") in drawn
    assert ("h4", "h5", "plan") in drawn


def test_a_rescue_shows_what_was_attacking_the_piece():
    # The knight on d5 is attacked by the pawn on e4 and has to move.
    board = chess.Board("4k3/8/8/3n4/4P3/8/8/4K3 b - - 0 1")
    move = chess.Move.from_uci("d5f6")
    rescue = next(p for p in explain_move(board, [move]) if p.kind == "rescues")
    drawn = [(line.origin, line.target, line.tone) for line in rescue.cue.arrows]
    assert ("d5", "f6", "move") in drawn
    assert ("e4", "d5", "threat") in drawn
