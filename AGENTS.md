# Repository notes

## What this is

`decodex` explains engine moves from verifiable facts. The hard rule: search and
static rules establish what is true, the report layer only verbalises it. Never
let a model infer chess content — that is what produces phantom pins.

## Layout

Leaf first, so the dependency direction is one-way:

- `decodex/values.py` — piece values, naming helpers, `with_turn`. Imports nothing
  of ours, so every other module can use it.
- `decodex/cues.py` — `Cue`, `Mark`, `Arrow`, `Insight`: the squares behind a
  statement. Also a leaf, since every detector attaches one.
- `decodex/assess.py` — evaluation to verdict sentence ("a decisive advantage").
- `decodex/motifs.py` — pins, skewers, batteries, forks, discovered attacks,
  attack/support relations. Pure geometry, written from scratch.
- `decodex/roles.py` — what each piece is doing.
- `decodex/concepts.py` — material, pawn structure, king safety, space, development.
- `decodex/plans.py` — purpose of a move, read out of the principal variation.
- `decodex/engine.py` — engine discovery, `RawEngine` for `eval` traces, parser
  for the NNUE derived piece values table.
- `decodex/facts.py` — SEE, hanging material, free-tempo threats, threat diffing,
  and `analyse_position`, which assembles everything above into `PositionFacts`.
- `decodex/game.py` — per-move classification, swing, game aggregates.
- `decodex/report.py` — text rendering, template-driven, plus the eval graph.
- `decodex/play.py` — play-vs-bot session state.
- `decodex/cli.py` — `position`, `game`, `play` subcommands.

Web service:

- `decodex/limits.py` — depth, size and rate ceilings for the public endpoint.
  Depth ceilings are overridable via `DECODEX_MAX_*` env vars, because a 0.1 vCPU
  host needs lower ones than a laptop.
- `decodex/pool.py` — the shared engine, lent out one request at a time.
  `DECODEX_LEAN=1` runs a single process for 512 MB hosts.
- `decodex/payload.py` — the same facts as JSON, for the browser.
- `decodex/web.py` — FastAPI app; `create_app(engine_path, rate_limits=...)`.
- `decodex/static/` — the UI. Plain HTML, CSS and JS, no build step.
- `Dockerfile`, `render.yaml`, `fly.toml`, `DEPLOY.md` — deployment.

## Environment

- Stockfish is not in apt here. Install 17.1 from the official GitHub release
  (avx2 build; the CPU has avx2/bmi2/avx512f). `/usr/local/bin` is not writable,
  so `~/.local/bin/stockfish` plus `DECODEX_ENGINE` is the working arrangement.
- `pip install -e ".[dev]"`, then `pytest`. Tests needing the engine are marked
  `engine`, so `pytest -m "not engine"` runs the rules-only subset.
- Run the UI with `uvicorn decodex.web:create_app --factory`. There is no module
  level `app`, so plain `decodex.web:app` fails.

## Things learned the hard way

- **Two engine processes are needed.** python-chess only speaks standard UCI, and
  the per-piece ablation table comes from Stockfish's non-standard `eval`. Hence
  `RawEngine` alongside `SimpleEngine`. Keep it long-lived; the NNUE net is
  133 MB and reloading per position is slow.
- **Do not `select()` on the engine pipe.** The buffered reader pulls several
  lines at once, so the sentinel sits in Python's buffer while the fd looks idle
  and the read times out. Blocking `readline` with a `threading.Timer` watchdog
  is correct.
- **Rebuild the board from FEN when handing a tempo**, rather than leaving a null
  move on the stack. python-chess warns "Not transmitting history with null moves
  to UCI engine" otherwise. See `facts.hand_tempo`.
- **Clamp move loss.** Mate scores are ±100000; uncapped, one missed mate makes
  average loss read 333 pawns per move. `MAX_LOSS_CP = 1000`.
- **Report mate as mate.** When a move walks into mate, print "mated in 1", not
  "eval +999.99". `MoveReview.allowed_mate` covers this.
- **`chess.pgn.Game` ships `"?"` placeholder headers**, so `setdefault` on White
  and Black silently does nothing. Assign directly.
- **Only claim material when SEE agrees.** The engine's best move being a capture
  does not mean it wins material; check `see(...) > 0` first. Likewise only quote
  a threat's gain when it is actually positive, or a lost position reads as
  "threatens ... (gains -7.60)".
- **A relation is only worth reporting when something is at stake.** Listing every
  defence produces "rook on d1 supports rook on h1" in the opening, which is true
  and useless. Require the defended piece to be under attack.
- **Mobility and pins need that side to be to move.** Asking `is_pinned` or
  counting legal moves on the opponent's turn reports every piece as frozen. Use
  `values.with_turn` first.
- **A piece on its starting square is undeveloped, not trapped.** Guard the "has
  no moves at all" label with `_is_undeveloped`, or move one reads as a disaster.
- **Filter geometry by value or it buries itself.** A bishop with a pawn behind it
  is technically a skewer; requiring the rear piece to be a knight or better
  leaves only the motifs a reader cares about. Batteries are found twice, once
  from each end, so collapse them per pair.
- **Purpose must come from the line, never from the move.** `plans.py` only claims
  an intention when the PV actually contains the follow-up. Anything else is
  inference dressed up as fact.
- **Credit for a good move needs the second-best line.** Playing the engine's
  choice is unremarkable when the alternative was just as good, so `review_game`
  searches `multipv=2` and `swing_cp` measures the gap.
- **Scale the eval graph to the game.** A fixed range flattens a quiet game into
  one repeated block.

## Web service lessons

- **The engine is global state.** `Skill Level` set for a weak bot move stays set
  for the whole process, so a single play request would otherwise cripple every
  later analysis for everyone. Restore it in a `finally`.
- **Rate limit in two tiers.** Searches cost CPU seconds; legality checks cost
  microseconds. One shared budget makes the board unusable long before the engine
  is under strain, so `/api/legal` gets its own generous bucket.
- **Bound the queue, not just the rate.** Without `MAX_QUEUE_DEPTH` a crowd simply
  grows the queue until everybody times out. Fast 503 beats slow failure.
- **Cap the limiter's own memory.** A dict keyed by client address is itself an
  exhaustion vector on a public endpoint.
- **Tests need the throttle open.** `create_app(rate_limits=...)` exists so
  functional tests are not silently answered with 429; the limiter is tested
  separately against its own app.
- **Docker: `COPY` preserves source permissions.** This checkout is `rw-rw----`,
  so the unprivileged runtime user could not read its own code. `chmod -R a+rX`
  after copying.
- **Docker: build Stockfish from source, `ARCH=x86-64`.** Release tarballs target
  avx2/bmi2 and die with SIGILL on hosts without them. `make net` needs curl
  present, and must run before `build`; skip `profile-build`, which doubles an
  already slow compile for perhaps 10%.

## Board rendering

- **a1 is dark.** a1 is fileIndex 0, rank 1, so a square is light exactly when
  `(fileIndex + rank)` is **even**. The first version had this inverted and the
  board looked subtly wrong in a way that is hard to see in a screenshot.
- **Geometry lives in `static/board.js`**, separate from the DOM, so it can be
  run under node and compared against python-chess. `tests/test_board_js.py`
  checks all 64 squares rather than a handful. Load order matters: `board.js`
  before `app.js`.
- **Draw from `boardOrder(flipped)`** rather than doing the flip arithmetic
  inline. It returns squares in drawing order with colour and coordinate flags
  attached, so orientation is decided in one tested place.
- **Pieces are lichess's cburnett SVGs** in `static/pieces/`, `wK.svg` style
  names, CC-BY-SA. Unicode chess glyphs render inconsistently across platforms
  and are what made the original board look broken.
- **Highlight with flat washes, not inset borders.** An `inset box-shadow` under
  an absolutely positioned piece reads as a rendering artefact.

## Cues: showing a fact as well as saying it

- **The geometry comes from the detector, never from the sentence.** A drawn arrow
  is another claim about the position. Parsing squares back out of the prose would
  reintroduce the guessing the rest of the project exists to avoid, so every
  detector returns its squares next to the words in a `Cue`.
- **An empty cue is a legitimate answer.** A concept about the whole position has
  nothing to point at; the UI then draws nothing rather than inventing a target.
  `Cue.__bool__` exists for exactly that check.
- **Four mark tones and five arrow tones, no more.** A reader learns a small
  vocabulary; twenty colours is decoration. Both are validated in `__post_init__`,
  so a typo fails at construction rather than rendering silently.
- **First tone wins per square.** Detectors pass the most specific role first, so
  a square that is both the actor and part of the swept line reads as the actor.
- **`squareCenter` must agree with `boardOrder`.** The grid and the arrow overlay
  are separate arithmetic; `tests/test_board_js.py` pins the overlay to the grid
  cell by cell, in both orientations, because an off-by-one here is invisible.
- **Arrows stop short of both squares**, further at the head, or they hide the very
  pieces they are about. Shorter than the two gaps combined and the line would
  invert, so `arrowGeometry` returns null instead.

## Hosting reality, early 2026

- **Measured footprint:** two engine processes cost ~675 MB resident, one costs
  ~310 MB. The 512 MB free tiers therefore need `DECODEX_LEAN=1`. Only the NNUE
  ablation panel needs the second process, so lean mode degrades one panel and
  keeps everything else.
- **On 0.1 vCPU** (Render free), depth 14 on one position takes ~5 s and a
  28-ply game review at depth 10 takes ~17 s. Usable, not fast. Verified in a
  container capped with `--memory 512m --cpus 0.1`.
- **Free tiers that no longer exist:** Fly.io (removed 2024), Heroku (2022),
  Hugging Face Docker Spaces (now needs PRO; static Spaces still free). Most
  online guides are stale on all three.
- **Render free still works** without a credit card, but sleeps after 15 minutes
  and takes ~50 s to wake because the NNUE net reloads. 750 instance-hours a
  month against 730 hours in a month, so an external pinger can keep it warm.
- **The permanent answer is client-side.** Stockfish compiles to WASM, which
  makes the whole thing static and free forever, at the cost of porting the fact
  layers to JS. Multi-threaded WASM needs COOP/COEP headers, which GitHub Pages
  does not send.

## Upstream references

- `ornicar/lichess-puzzler`, `tagger/cook.py` — tested motif detectors, but
  AGPL-3.0. Deliberately **not** used: `decodex/motifs.py` is written from the
  geometry so the project stays unencumbered. Useful only as a cross-check on
  which motifs are worth detecting.
- `rlefko/chessbeast` — Stockfish + SF16 classical + Maia2 + LLM, gRPC services.
- `whythismove.com/open-source` — MIT, full platform with Maia-2.
- `ronaldsuwandi/thinkfish` — documents what LLM hallucination looks like here.
- Stockfish 17 removed the classical hand-crafted eval, so term-by-term
  breakdowns (king safety, mobility) need a Stockfish 16 binary alongside.
