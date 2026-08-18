"""Static analysis layers: no engine required."""

import chess

from decodex.assess import Assessment
from decodex.concepts import (
    describe_concepts,
    doubled_pawns,
    isolated_pawns,
    king_shelter_count,
    material_count,
    passed_pawns,
    space,
    undeveloped,
)
from decodex.motifs import (
    find_alignments,
    find_batteries,
    find_discovered_attacks,
    find_forks,
    relation_insights,
    tactic_insights,
)
from decodex.facts import line_plies
from decodex.plans import explain_move
from decodex.roles import describe_roles
from decodex.values import join_words, with_turn

# The position the user brought from DecodeChess, move 15 of a Sicilian Dragon.
DRAGON = "2r1k2r/1pq1ppbp/p2pbnp1/8/3BP1P1/1BN2P2/PPPQ3P/1K1R3R w k - 1 15"


def relation_texts(board: chess.Board) -> list[str]:
    """The relation sentences alone, for tests about wording and ordering."""
    return [item.text for item in relation_insights(board)]


def test_assessment_bands_run_from_equal_to_decisive():
    assert Assessment(cp_white=10).phrase == "equal"
    assert Assessment(cp_white=60).phrase == "a slight edge"
    assert Assessment(cp_white=120).phrase == "a clear edge"
    assert Assessment(cp_white=250).phrase == "a serious advantage"
    assert Assessment(cp_white=450).phrase == "a decisive advantage"
    assert Assessment(cp_white=350).phrase == "a winning advantage"
    assert Assessment(cp_white=448).phrase == "a decisive advantage"
    assert Assessment(cp_white=900).phrase == "a decisive advantage"


def test_assessment_names_the_side_that_is_better():
    assert Assessment(cp_white=448).leader == chess.WHITE
    assert Assessment(cp_white=-448).leader == chess.BLACK
    assert Assessment(cp_white=12).leader is None


def test_assessment_reads_like_decodechess():
    assert Assessment(cp_white=448).describe() == "White has a decisive advantage (4.48)."
    assert Assessment(cp_white=-250).describe() == "Black has a serious advantage (2.50)."
    assert Assessment(cp_white=5).describe() == "The position is balanced (+0.05)."


def test_assessment_prefers_mate_over_centipawns():
    assert Assessment(cp_white=100000, mate=3).describe() == "White mates in 3."
    assert Assessment(cp_white=-100000, mate=-2).describe() == "Black mates in 2."


def test_assessment_handles_a_missing_evaluation():
    assert Assessment(cp_white=None).describe() == "No evaluation available."


def test_with_turn_flips_the_side_without_moving_anything():
    board = chess.Board(DRAGON)
    handed = with_turn(board, chess.BLACK)
    assert handed.turn == chess.BLACK
    assert handed.piece_map() == board.piece_map()
    assert with_turn(board, chess.WHITE) is board


def test_join_words_reads_as_english():
    assert join_words(["rook on c7"]) == "the rook on c7"
    assert join_words(["rook on c7", "king on e7"]) == "the rook on c7 and the king on e7"
    assert join_words(["a", "b", "c"]) == "the a, the b and the c"


def test_pin_is_found_against_the_dearer_piece_behind():
    # Bd4 hits Nf6 with Bg7 behind it: the knight cannot step aside for free.
    alignments = find_alignments(chess.Board(DRAGON), chess.WHITE)
    kinds = {(a.kind, chess.square_name(a.near), chess.square_name(a.far)) for a in alignments}
    assert ("pin", "f6", "g7") in kinds


def test_pin_against_the_king_is_absolute():
    # White bishop on g5, black knight f6, black king e7 behind it.
    board = chess.Board("4k3/8/5n2/6B1/8/8/8/4K3 b - - 0 1")
    board.set_piece_at(chess.E7, chess.Piece(chess.KING, chess.BLACK))
    board.remove_piece_at(chess.E8)
    pins = [a for a in find_alignments(board, chess.WHITE) if a.kind == "pin"]
    assert pins and pins[0].absolute
    assert "absolutely pinned" in pins[0].describe(board)


def test_skewer_puts_the_dearer_piece_in_front():
    # Rook on a1 hits the queen on a5 with a rook on a8 behind it.
    board = chess.Board("r3k3/8/8/q7/8/8/8/R3K3 w - - 0 1")
    skewers = [a for a in find_alignments(board, chess.WHITE) if a.kind == "skewer"]
    assert skewers
    assert chess.square_name(skewers[0].near) == "a5"
    assert "skewered" in skewers[0].describe(board)


def test_a_pawn_behind_a_piece_is_not_worth_calling_a_skewer():
    # Bb3 hits Be6 with only the f7 pawn behind it. Geometrically a skewer,
    # but reporting it would bury the real motifs.
    alignments = find_alignments(chess.Board(DRAGON))
    pairs = {(chess.square_name(a.near), chess.square_name(a.far)) for a in alignments}
    assert ("e6", "f7") not in pairs


def test_battery_notes_what_it_is_aimed_at():
    batteries = [b for b in find_batteries(chess.Board(DRAGON)) if b.target is not None]
    described = [b.describe(chess.Board(DRAGON)) for b in batteries]
    assert any("rook on c8 stands behind the queen on c7" in text for text in described)
    assert any("knight on c3" in text for text in described)


def test_batteries_are_reported_once_per_pair():
    batteries = find_batteries(chess.Board(DRAGON))
    pairs = [frozenset((b.front, b.rear)) for b in batteries]
    assert len(pairs) == len(set(pairs))


def test_knight_fork_names_both_targets():
    board = chess.Board("8/2r1k3/8/8/1N6/8/8/4K3 w - - 0 1")
    forks = find_forks(board)
    assert forks
    described = forks[0].describe()
    assert described.startswith("Nd5+ checks and forks")
    assert "rook on c7" in described and "king on e7" in described


def test_a_lone_attack_is_not_a_fork():
    assert find_forks(chess.Board("4k3/8/8/8/4N3/8/8/4K3 w - - 0 1")) == []


def test_discovered_attack_names_the_uncovered_piece():
    # Ra1 is screened by the knight on a4; moving it unveils the rook on Qa8.
    board = chess.Board("q3k3/8/8/8/N7/8/8/R3K3 w - - 0 1")
    found = find_discovered_attacks(board)
    assert found
    assert all("uncovers the rook on a1" in item.describe() for item in found)
    assert all("queen on a8" in item.describe() for item in found)


def test_relations_put_captures_before_defences():
    lines = relation_texts(chess.Board(DRAGON))
    first_support = next(i for i, text in enumerate(lines) if "supports" in text)
    assert all("can capture" in text for text in lines[:first_support])


def test_relations_match_what_decodechess_points_out():
    lines = relation_texts(chess.Board(DRAGON))
    assert "the black bishop on e6 can capture the white bishop on b3" in lines
    assert "the white pawn on a2 supports the white bishop on b3" in lines


def test_defence_of_an_unattacked_piece_is_not_worth_a_line():
    # Rd1 guards Rh1, but nothing is attacking Rh1, so it says nothing useful.
    lines = relation_texts(chess.Board(DRAGON))
    assert "the white rook on d1 supports the white rook on h1" not in lines


def test_tactics_lead_with_standing_geometry():
    items = tactic_insights(chess.Board(DRAGON))
    assert items
    assert "pinned" in items[0].text


def test_purpose_reads_the_follow_up_out_of_the_line():
    board = chess.Board(DRAGON)
    pv = []
    walker = board.copy()
    for san in ("h4", "Rg8", "h5"):
        move = walker.parse_san(san)
        pv.append(move)
        walker.push(move)
    purposes = [p.describe() for p in explain_move(board, pv)]
    assert "intends to play h5" in purposes


def test_purpose_reads_a_prepared_advance_out_of_the_line():
    board = chess.Board(DRAGON)
    pv = []
    walker = board.copy()
    for san in ("h4", "Rg8", "g5"):
        move = walker.parse_san(san)
        pv.append(move)
        walker.push(move)
    purposes = [p.describe() for p in explain_move(board, pv)]
    assert "supports advancing the pawn to g5" in purposes


def test_no_line_means_no_claimed_purpose():
    assert explain_move(chess.Board(), []) == []


def test_line_plies_keep_each_move_and_its_squares():
    board = chess.Board(DRAGON)
    pv = []
    walker = board.copy()
    for san in ("h4", "Rg8", "h5"):
        move = walker.parse_san(san)
        pv.append(move)
        walker.push(move)
    plies = line_plies(board, pv)
    assert [ply.san for ply in plies] == ["h4", "Rg8", "h5"]
    assert plies[0].move_number == 15
    assert plies[0].cue.arrows[0].tone == "move"
    assert plies[1].fen_before != plies[0].fen_before
    assert plies[0].fen_after == plies[1].fen_before
    assert any("intends to play h5" in p.describe() for p in plies[0].purposes)
    assert plies[2].uci == "h4h5"

def test_capture_in_the_line_is_named_as_a_purpose():
    board = chess.Board(DRAGON)
    pv = []
    walker = board.copy()
    for san in ("h4", "Bxb3", "axb3"):
        move = walker.parse_san(san)
        pv.append(move)
        walker.push(move)
    plies = line_plies(board, pv)
    assert any("captures the white bishop" in p.describe() for p in plies[1].purposes)
    assert any("captures the black bishop" in p.describe() for p in plies[2].purposes)
    assert any("counters the threat" in p.describe() for p in plies[2].purposes)
    recapture = next(p for p in plies[2].purposes if "captures the black bishop" in p.describe())
    assert "takes the black bishop" in recapture.detail
    counter = next(p for p in plies[2].purposes if "counters the threat" in p.describe())
    assert "no longer legal" in counter.detail


def test_purpose_reports_castling_and_promotion():
    castle = chess.Board("4k3/8/8/8/8/8/8/4K2R w K - 0 1")
    assert "castles short, tucking the king away" in [
        p.describe() for p in explain_move(castle, [castle.parse_san("O-O")])
    ]
    promote = chess.Board("8/P7/8/8/8/8/8/4K2k w - - 0 1")
    assert "promotes to a queen" in [
        p.describe() for p in explain_move(promote, [promote.parse_san("a8=Q")])
    ]


def test_role_reports_a_sole_defender():
    # Only f7 holds the bishop on e6, which Bb3 is attacking.
    roles = describe_roles(chess.Board(DRAGON), chess.BLACK)
    described = [r.describe() for r in roles]
    assert any(
        "pawn on f7 is the only defender of the bishop on e6" in text
        for text in described
    )


def test_role_ignores_defence_of_a_piece_nobody_is_attacking():
    # Rd1 guards Rh1, but nothing is attacking it, so it is not a duty.
    described = [r.describe() for r in describe_roles(chess.Board(DRAGON), chess.WHITE)]
    assert not any("defends the rook on h1" in text for text in described)


def test_role_says_nothing_about_untouched_opening_pieces():
    # Everything guards something at move one; none of it means anything yet.
    described = [r.describe() for r in describe_roles(chess.Board(), chess.WHITE)]
    assert not any("only defender" in text for text in described)
    assert not any("has no moves at all" in text for text in described)


def test_role_reports_attacks_and_open_files():
    described = [r.describe() for r in describe_roles(chess.Board(DRAGON), chess.WHITE)]
    assert any("attacks the knight on f6" in text for text in described)
    assert any("half-open file" in text for text in described)


def test_role_mobility_is_judged_with_that_side_to_move():
    # Black's pieces have moves; asking on a White-to-move board would report
    # every black piece as frozen.
    described = [r.describe() for r in describe_roles(chess.Board(DRAGON), chess.BLACK)]
    assert not any("has no moves at all" in text for text in described)


def test_role_reports_a_genuinely_trapped_piece():
    # The bishop has left home and run out of squares: g7 and h7 block it in.
    board = chess.Board("7b/6pp/8/8/8/8/8/K6k b - - 0 1")
    described = [r.describe() for r in describe_roles(board, chess.BLACK)]
    assert any(
        "bishop on h8" in text and "has no moves at all" in text for text in described
    )


def test_material_count_excludes_the_king():
    board = chess.Board()
    # Eight pawns, two knights, two bishops, two rooks, one queen.
    assert material_count(board, chess.WHITE) == 8 * 100 + 2 * 320 + 2 * 330 + 2 * 500 + 900
    assert material_count(board, chess.WHITE) == material_count(board, chess.BLACK)


def test_pawn_structure_detectors():
    # White is doubled on the c file; black's h5 pawn has nothing in its way.
    board = chess.Board("4k3/8/8/7p/8/2P5/1PP5/4K3 w - - 0 1")
    assert doubled_pawns(board, chess.WHITE) == ["c"]
    assert isolated_pawns(board, chess.WHITE) == []
    assert passed_pawns(board, chess.BLACK) == ["h5"]


def test_isolated_pawn_has_no_friendly_pawn_on_either_neighbouring_file():
    board = chess.Board("4k3/8/8/8/8/8/P3P3/4K3 w - - 0 1")
    assert isolated_pawns(board, chess.WHITE) == ["a2", "e2"]
    # Give the a pawn a neighbour on b and it is no longer isolated.
    board.set_piece_at(chess.B2, chess.Piece(chess.PAWN, chess.WHITE))
    assert isolated_pawns(board, chess.WHITE) == ["e2"]


def test_passed_pawn_is_blocked_by_a_neighbouring_file():
    board = chess.Board("4k3/8/8/8/1p6/P7/8/4K3 w - - 0 1")
    assert passed_pawns(board, chess.WHITE) == []


def test_king_shelter_counts_pawns_in_front_of_the_king():
    board = chess.Board(DRAGON)
    # White has castled long behind a2, b2, c2.
    assert king_shelter_count(board, chess.WHITE) == 3


def test_space_counts_only_the_far_half():
    board = chess.Board(DRAGON)
    assert space(board, chess.WHITE) > space(board, chess.BLACK)


def test_undeveloped_counts_pieces_still_at_home():
    assert len(undeveloped(chess.Board(), chess.WHITE)) == 6
    assert undeveloped(chess.Board(DRAGON), chess.WHITE) == ["h1"]


def test_concepts_omit_features_that_are_level():
    names = [c.name for c in describe_concepts(chess.Board())]
    assert "Material" not in names
    assert "Development" not in names


def test_concepts_name_the_side_a_feature_favours():
    board = chess.Board("4k3/8/8/8/8/8/PPP5/4K3 w - - 0 1")
    concepts = {c.name: c for c in describe_concepts(board)}
    assert concepts["Material"].favours == chess.WHITE
    assert "3.00 ahead" in concepts["Material"].detail


def test_purpose_and_concept_payloads_include_expandable_detail():
    from decodex.payload import position_payload
    from decodex.facts import PositionFacts
    from decodex.plans import Purpose
    from decodex.concepts import Concept
    from decodex.cues import EMPTY

    facts = PositionFacts(
        fen=DRAGON,
        perspective=chess.WHITE,
        turn=chess.WHITE,
        free_tempo_view=False,
        eval_cp=259,
        purposes=[
            Purpose(
                kind="captures",
                text="captures the black bishop",
                ply=0,
                cue=EMPTY,
                detail="axb3 takes the black bishop on b3.",
                line="16. axb3 O-O",
            )
        ],
        concepts=[
            Concept(
                name="Space",
                detail="pawn-controlled squares in enemy territory 4 vs 2",
                favours=chess.WHITE,
                white_squares=(chess.G5,),
                black_squares=(chess.E4,),
            )
        ],
    )
    payload = position_payload(facts)
    purpose = payload["purposes"][0]
    assert purpose["detail"].startswith("axb3 takes")
    assert purpose["line"] == "16. axb3 O-O"
    concept = payload["concepts"][0]
    assert "White squares counted: g5" in concept["explanation"]
    assert "This favours White" in concept["explanation"]
