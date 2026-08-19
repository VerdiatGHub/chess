"""Opening name detection from a sequence of moves, with detailed variations."""

from typing import List, Optional

import chess

# Each key is a tuple of UCI moves that define an opening line.
# The longest matching prefix is returned. Order does not matter, only length.
OPENINGS: dict[tuple[str, ...], str] = {
    # --- Sicilian Defence ---
    ("e2e4", "c7c5"): "Sicilian Defence",
    ("e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "g7g6"): "Sicilian Dragon",
    ("e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "g7g6", "c1e3", "f8g7"): "Sicilian Dragon, Yugoslav Attack",
    ("e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "e7e6"): "Sicilian Scheveningen",
    ("e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "e7e6", "f2f4"): "Sicilian Scheveningen, Keres Attack",
    ("e2e4", "c7c5", "g1f3", "e7e6", "d2d4", "c5d4", "f3d4", "a7a6"): "Sicilian Kan",
    ("e2e4", "c7c5", "g1f3", "e7e6", "d2d4", "c5d4", "f3d4", "b8c6"): "Sicilian Taimanov",
    ("e2e4", "c7c5", "g1f3", "b8c6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "e7e5"): "Sicilian Sveshnikov",
    ("e2e4", "c7c5", "g1f3", "b8c6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "e7e5", "d4b5"): "Sicilian Sveshnikov, Chelyabinsk Variation",
    ("e2e4", "c7c5", "g1f3", "b8c6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "d7d6"): "Sicilian Classical",
    ("e2e4", "c7c5", "g1f3", "b8c6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "d7d6", "c1g5"): "Sicilian Classical, Richter-Rauzer",
    ("e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "a7a6"): "Sicilian Najdorf",
    ("e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "a7a6", "c1g5"): "Sicilian Najdorf, English Attack",
    ("e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "a7a6", "f1e2"): "Sicilian Najdorf, Opocensky Variation",
    ("e2e4", "c7c5", "g1f3", "d7d6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "a7a6", "f2f4"): "Sicilian Najdorf, Polugaevsky Variation",
    ("e2e4", "c7c5", "g1f3", "e7e6", "d2d4", "c5d4", "f3d4", "g8f6", "b1c3", "b8c6"): "Sicilian Four Knights",
    ("e2e4", "c7c5", "b1c3"): "Sicilian, Closed",
    ("e2e4", "c7c5", "b1c3", "b8c6", "g1f3"): "Sicilian, Closed, Botvinnik",
    # --- Open Game (1.e4 e5) ---
    ("e2e4", "e7e5"): "Open Game",
    ("e2e4", "e7e5", "g1f3"): "King's Knight Opening",
    ("e2e4", "e7e5", "g1f3", "b8c6"): "Ruy Lopez / Italian / Scotch",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4"): "Italian Game",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5"): "Giuoco Piano",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5", "c2c3"): "Giuoco Piano, Main Line",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6"): "Two Knights Defence",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5"): "Ruy Lopez",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"): "Ruy Lopez, Morphy Defence",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4"): "Ruy Lopez, Morphy Defence, Exchange Variation",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5c6"): "Ruy Lopez, Morphy Defence, Exchange Variation, deferred",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6"): "Ruy Lopez, Morphy Defence, Main Line",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6", "e1g1"): "Ruy Lopez, Morphy Defence, Closed",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6", "b5a4", "g8f6", "e1g1", "b7b5", "a4b3"): "Ruy Lopez, Morphy Defence, Closed, Main Line",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6"): "Ruy Lopez, Berlin Defence",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "g8f6", "e1g1"): "Ruy Lopez, Berlin Defence, Main Line",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "f8c5"): "Ruy Lopez, Classical Defence",
    ("e2e4", "e7e5", "g1f3", "b8c6", "d2d4"): "Scotch Game",
    ("e2e4", "e7e5", "g1f3", "b8c6", "d2d4", "e5d4", "f3d4"): "Scotch Game, Main Line",
    ("e2e4", "e7e5", "g1f3", "b8c6", "d2d4", "e5d4", "f3d4", "g8f6", "d4c6"): "Scotch Game, Mieses Variation",
    ("e2e4", "e7e5", "g1f3", "g8f6"): "Petrov Defence",
    ("e2e4", "e7e5", "g1f3", "g8f6", "f3e5"): "Petrov Defence, Classical Variation",
    ("e2e4", "e7e5", "f2f4"): "King's Gambit",
    ("e2e4", "e7e5", "f2f4", "e5f4"): "King's Gambit Accepted",
    ("e2e4", "e7e5", "f2f4", "d7d5"): "King's Gambit Declined, Falkbeer Counter-Gambit",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5", "c2c3", "g8f6"): "Giuoco Piano, Main Line",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5", "d2d3"): "Giuoco Pianissimo",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "d7d6"): "Ruy Lopez, Steinitz Defence",
    ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "d7d6", "d2d4"): "Ruy Lopez, Steinitz Defence, Classical Variation",
    ("e2e4", "e7e5", "d2d4"): "Centre Game",
    ("e2e4", "e7e5", "d2d4", "e5d4"): "Centre Game, Main Line",
    ("e2e4", "e7e5", "b1c3"): "Vienna Game",
    ("e2e4", "e7e5", "b1c3", "g8f6"): "Vienna Game, Main Line",
    ("e2e4", "e7e5", "b1c3", "b8c6", "g1f3"): "Vienna Game, Max Lange",
    # --- Semi-Open (1.e4, other replies) ---
    ("e2e4", "c7c6"): "Caro-Kann Defence",
    ("e2e4", "c7c6", "d2d4", "d7d5", "e4d5"): "Caro-Kann, Exchange Variation",
    ("e2e4", "c7c6", "d2d4", "d7d5", "b1c3"): "Caro-Kann, Classical Variation",
    ("e2e4", "c7c6", "d2d4", "d7d5", "b1c3", "d5e4", "c3e4"): "Caro-Kann, Classical Variation, Main Line",
    ("e2e4", "c7c6", "d2d4", "d7d5", "e4d5", "c6d5", "c2c4"): "Caro-Kann, Panov Attack",
    ("e2e4", "c7c6", "d2d4", "d7d5", "g1f3"): "Caro-Kann, Fantasy Variation",
    ("e2e4", "e7e6"): "French Defence",
    ("e2e4", "e7e6", "d2d4", "d7d5"): "French Defence, Main Line",
    ("e2e4", "e7e6", "d2d4", "d7d5", "b1c3"): "French Defence, Classical Variation",
    ("e2e4", "e7e6", "d2d4", "d7d5", "b1c3", "g8f6"): "French Defence, Classical Variation, Main Line",
    ("e2e4", "e7e6", "d2d4", "d7d5", "e4d5"): "French Defence, Exchange Variation",
    ("e2e4", "e7e6", "d2d4", "d7d5", "b1c3", "f8b4"): "French Defence, Winawer Variation",
    ("e2e4", "e7e6", "d2d4", "d7d5", "b1c3", "f8b4", "e4e5"): "French Defence, Winawer, Advance Variation",
    ("e2e4", "e7e6", "d2d4", "d7d5", "g1f3"): "French Defence, Tarrasch Variation",
    ("e2e4", "d7d5"): "Scandinavian Defence",
    ("e2e4", "d7d5", "e4d5"): "Scandinavian Defence, Main Line",
    ("e2e4", "d7d5", "e4d5", "d8d5"): "Scandinavian Defence, Main Line, 2...Qxd5",
    ("e2e4", "g7g6"): "Modern Defence",
    ("e2e4", "b7b6"): "Owen Defence",
    ("e2e4", "b8c6"): "Nimzowitsch Defence",
    # --- Closed / Queen's Pawn (1.d4) ---
    ("d2d4"): "Queen's Pawn Game",
    ("d2d4", "d7d5"): "Queen's Pawn Game, 1...d5",
    ("d2d4", "d7d5", "c2c4"): "Queen's Gambit",
    ("d2d4", "d7d5", "c2c4", "e7e6"): "Queen's Gambit Declined",
    ("d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6"): "Queen's Gambit Declined, Main Line",
    ("d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "g8f6", "c1g5"): "Queen's Gambit Declined, Classical Variation",
    ("d2d4", "d7d5", "c2c4", "e7e6", "b1c3", "f8b4"): "Queen's Gambit Declined, Ragozin Variation",
    ("d2d4", "d7d5", "c2c4", "c7c6"): "Slav Defence",
    ("d2d4", "d7d5", "c2c4", "c7c6", "g1f3", "g8f6", "b1c3"): "Semi-Slav Defence",
    ("d2d4", "d7d5", "c2c4", "c7c6", "g1f3", "g8f6", "b1c3", "e7e6"): "Semi-Slav Defence, Main Line",
    ("d2d4", "d7d5", "c2c4", "c7c6", "g1f3", "g8f6", "e2e3"): "Slav Defence, Main Line",
    ("d2d4", "d7d5", "c2c4", "e7e6", "g1f3"): "Queen's Gambit Declined, Orthodox Defence",
    ("d2d4", "g8f6"): "Indian Game",
    ("d2d4", "g8f6", "c2c4"): "Indian Defence",
    ("d2d4", "g8f6", "c2c4", "e7e6"): "Nimzo-Indian Defence",
    ("d2d4", "g8f6", "c2c4", "e7e6", "b1c3", "f8b4"): "Nimzo-Indian Defence, Main Line",
    ("d2d4", "g8f6", "c2c4", "e7e6", "g1f3"): "Queen's Indian Defence",
    ("d2d4", "g8f6", "c2c4", "e7e6", "g1f3", "b7b6"): "Queen's Indian Defence, Main Line",
    ("d2d4", "g8f6", "c2c4", "g7g6"): "King's Indian Defence",
    ("d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "f8g7"): "King's Indian Defence, Main Line",
    ("d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "f8g7", "e2e4"): "King's Indian Defence, Classical Variation",
    ("d2d4", "g8f6", "c2c4", "g7g6", "b1c3", "d7d6"): "King's Indian Defence, Fianchetto Variation",
    ("d2d4", "g8f6", "c2c4", "e7e6", "b1c3", "f8b4", "d1c2"): "Nimzo-Indian, Classical Variation",
    ("d2d4", "g8f6", "c2c4", "e7e6", "b1c3", "f8b4", "a2a3"): "Nimzo-Indian, Saemisch Variation",
    ("d2d4", "g8f6", "c2c4", "c7c5"): "Benoni Defence",
    ("d2d4", "g8f6", "c2c4", "c7c5", "d4d5"): "Benoni Defence, Main Line",
    ("d2d4", "g8f6", "c2c4", "c7c5", "d4d5", "e7e6"): "Benoni Defence, Modern",
    ("d2d4", "g8f6", "c2c4", "d7d6"): "Old Indian Defence",
    ("d2d4", "g8f6", "c2c4", "d7d6", "b1c3"): "Old Indian Defence, Main Line",
    ("d2d4", "g8f6", "c2c4", "b7b6"): "Queen's Indian Defence",
    ("d2d4", "g8f6", "c2c4", "b7b6", "g1f3"): "Queen's Indian Defence, Main Line",
    # --- English (1.c4) ---
    ("c2c4"): "English Opening",
    ("c2c4", "e7e5"): "English, King's English",
    ("c2c4", "e7e5", "b1c3"): "English, King's English, Main Line",
    ("c2c4", "e7e5", "g1f3"): "English, King's English, Reversed Sicilian",
    ("c2c4", "g8f6"): "English, Nf6",
    ("c2c4", "c7c5"): "English, Symmetrical",
    ("c2c4", "c7c5", "b1c3"): "English, Symmetrical, Main Line",
    ("c2c4", "c7c5", "g1f3"): "English, Symmetrical, Botvinnik",
    # --- Reti (1.Nf3) ---
    ("g1f3"): "Reti Opening",
    ("g1f3", "d7d5"): "Reti Opening, 1...d5",
    ("g1f3", "d7d5", "c2c4"): "Reti Opening, Anglo-Slav",
    ("g1f3", "g8f6"): "Reti Opening, Nf6",
    # --- Other first moves ---
    ("b1c3"): "Van Geet Opening",
    ("b2b3"): "Nimzo-Larsen Attack",
    ("g2g3"): "King's Fianchetto Opening",
    ("e2e3"): "Van 't Kruijs Opening",
    ("d2d3"): "Mieses Opening",
    ("c2c3"): "Saragoza Opening",
    ("f2f4"): "Bird Opening",
    ("f2f4", "d7d5"): "Bird Opening, 1...d5",
    ("f2f4", "e7e5"): "Bird Opening, From Gambit",
    ("a2a3"): "Anderssen Opening",
    ("h2h3"): "Clemenz Opening",
}


def opening_name(moves: List[str]) -> Optional[str]:
    """Return the name of the opening that matches the longest prefix of `moves`.

    `moves` is a list of UCI strings (e.g., 'e2e4', 'c7c5'). The function
    returns the opening name if a prefix matches, otherwise None.
    """
    best: Optional[str] = None
    best_len = 0
    for seq, name in OPENINGS.items():
        if len(seq) <= len(moves) and moves[:len(seq)] == list(seq):
            if len(seq) > best_len:
                best_len = len(seq)
                best = name
    return best


def opening_name_from_board(board: chess.Board) -> Optional[str]:
    """Return the opening name from the board's move history."""
    moves = [move.uci() for move in board.move_stack]
    return opening_name(moves)
