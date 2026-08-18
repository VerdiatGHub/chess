# decodex

Explains why the engine's move is good, using only facts that can be checked.

The design constraint is that no component is allowed to reason about chess in
prose. Stockfish and a set of static rules establish what is true; the reporting
layer only puts those facts into words. This is what keeps the output free of the
invented pins and phantom pieces that appear when a language model is handed a
position and asked to explain it.

Everything here is free: Stockfish is GPL, python-chess is MIT, and no network
service is involved.

## Install

```bash
pip install -e ".[dev]"
```

Stockfish must be on `PATH`, or pass `--engine /path/to/stockfish`, or set
`DECODEX_ENGINE`.

## Analyse a position

```bash
decodex position --fen "2r1k2r/1pq1ppbp/p2pbnp1/8/3BP1P1/1BN2P2/PPPQ3P/1K1R3R w k - 1 15" --side white
```

```
=== Position analysis for White ===
Summary        White has a serious advantage (2.22).
Evaluation     +2.22 (white's point of view)

Best moves for White
  1. h4              +2.45
     line: 15. h4 Rg8 16. h5 gxh5 17. gxh5 Bh8 18. h6 b5

h4 is good because it
  - intends to play h5

Threats
  before: Black intends b5, with nothing concrete yet
  after h4: Black intends Rg8, with nothing concrete yet

Tactics on the board
  - the black knight on f6 is pinned to the bishop on g7 by the white bishop on d4
  - the black rook on c8 stands behind the queen on c7, aimed at the white knight on c3

Pay attention to
  - the white bishop on b3 can capture the black bishop on e6
  - the white pawn on a2 supports the white bishop on b3

Piece roles for White
  - the white bishop on d4 defends the knight on c3, and attacks the knight on f6
  - the white rook on d1 stands on a half-open file

Concepts
  Space: pawn-controlled squares in enemy territory 3 vs 0 (White)

Piece importance for White (NNUE removal ablation, in pawns)
  queen   d2   8.38   (gains 1.02 after the best move)
```

`--side` takes `white`, `black`, or `both`. Asking about the side that is not to
move analyses the position as if that side were handed a free tempo, which is how
their own plans become visible.

## Analyse a game

```bash
decodex game --pgn game.pgn --side both
decodex game --moves "e4 e5 Bc4 Nc6 Qh5 Nf6 Qxf7#" --side black --all-moves
```

```
Graph          ▅▅▅▅▅▅▅▅▅▅▅▅▅▆▆▆▆▆▆▆▆██▇▇███
               white at the top, black at the bottom, full height is 2.43

--- White ---
Clean moves    100%
Average loss   0.03 per move
Breakdown      13 best, 1 excellent
Turning points none — no inaccuracies or worse
Good moves
  10. Bxd4     clearly best, 0.85 better than Qxd4
```

Every move is scored against the engine's preference for that position. Errors
surface as turning points, and best moves that were genuinely hard to find
surface as good moves. `--side` works as above.

## Play the bot and decode as you go

```bash
decodex play --color white --skill 5
```

At the prompt: play a move in SAN or UCI, then `decode [side]` for the current
position, `review [side]` for the game so far, or `roles [side]`, `concepts` and
`tactics` for a single panel without the full report. Also `board`, `pgn`,
`undo`, `help`, `quit`.

## Run it as a website

```bash
pip install -e ".[web]"
uvicorn decodex.web:create_app --factory --port 8000
```

Then open <http://localhost:8000>. Three tabs matching the CLI: a position to
decode, a game to review, and a game against the bot with analysis available
mid-game. There is a light and a dark theme, remembered between visits.

Every statement is also drawn: hover a line and the squares it was derived from
light up on the board, with arrows for the moves, attacks and defences it names.
Click to pin it, which is how it works on a touchscreen. The geometry comes from
the same detector that wrote the sentence, so the drawing cannot disagree with
the words — and a fact with nothing to point at draws nothing rather than
guessing.

The board uses lichess's cburnett piece set (`decodex/static/pieces/`, CC-BY-SA)
on their standard brown squares, rather than Unicode chess glyphs, which render
inconsistently across platforms. Board geometry lives in `decodex/static/board.js`
apart from the DOM so it can be tested against python-chess directly.

Or with Docker, which builds Stockfish from source so no engine install is
needed:

```bash
docker build -t decodex .
docker run -p 8000:8000 decodex
```

### Deploying it publicly

See **[DEPLOY.md](DEPLOY.md)** for the current state of the free options, which
is less rosy than most guides suggest — Fly and Heroku no longer have free tiers,
and Hugging Face now needs PRO for Docker Spaces.

The short version: **Render's free plan works** and `render.yaml` is configured
for it. Push to GitHub, then New → Blueprint on Render. It sleeps after 15
minutes idle and takes ~50 seconds to wake, which an external pinger every 10
minutes will prevent.

On a 512 MB host, set `DECODEX_LEAN=1`. That runs one engine process instead of
two, ~310 MB instead of ~675 MB. The only casualty is the NNUE piece-importance
panel, which needs a second Stockfish to answer `eval`; every other fact is
unaffected.

The endpoint is unauthenticated by design, so every request is bounded before it
reaches the engine:

| Guard | Limit |
| --- | --- |
| Search depth | 18 for a position, 12 for a game |
| Game length | 160 half-moves |
| Input size | 120 chars of FEN, 24 KB of PGN |
| Analysis calls | 12 burst, then 1 every 2 seconds per caller |
| Rules calls | 90 burst, then 8 per second per caller |
| Concurrent queue | 8 waiting, then 503 |
| Engine hold | 60 seconds, then abandoned |

Two things are worth understanding before you put this behind a domain.

Analysis is CPU-bound and serialised. One Stockfish process serves everyone,
behind a lock, because a second concurrent search would contend for the same
cores and make both slower. Scale by adding machines, not workers or threads.

The rate limiter keys on client address, which is spoofable. It exists to keep
the service usable under casual load, not to establish identity. If you need
real protection, put Cloudflare in front.

Sizing: 1 GB of memory is the floor, since the NNUE network alone is 133 MB.
Avoid platforms that spin down when idle — a cold start reloads that network
before answering, which reads to a visitor as a broken site.

## What the facts are

Search-derived:

- **Candidate moves** — MultiPV search, with the full line in SAN.
- **Threats** — measured by handing a side a free tempo and searching. The
  difference between the threats before and after a move is what the move
  defuses or concedes.
- **Purpose** — read out of the principal variation. The same piece moving again
  later in the line is an intention; another piece landing on a square this move
  newly defends is preparation. No follow-up in the line means no claim.
- **Piece importance** — Stockfish's own NNUE derived piece values, which are the
  evaluation change when each piece is removed from the board.
- **Move quality** — evaluation loss against the engine's choice, with the gap to
  the second-best move deciding whether finding it deserves credit.

Static, no engine needed:

- **Loose material** — static exchange evaluation, so a defended piece is not
  reported as free.
- **Tactics** — pins, skewers, batteries, forks and discovered attacks, from
  board geometry.
- **Piece roles** — what each piece defends, attacks, blocks, or is stuck doing.
- **Concepts** — material, pawn structure, king safety, space, development.
- **Attention list** — which pieces bear on which, ranked by what is at stake.

## Tests

```bash
pytest                      # everything
pytest -m "not engine"      # rules only, no engine needed
```

Engine-backed tests use positions where the right answer is forced, so they check
that the extracted facts are true rather than merely well formed. The static
layers are tested exhaustively without an engine.

## Not built yet

- Maia for human-move probability, which turns "this is best" into "this is best
  and hard to find at your rating".
- A language layer over the fact objects. The facts are already structured for
  it; the model must be instructed to translate only, never to infer.
