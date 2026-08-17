# Deploying decodex

The service is one Docker container with no database and no persistent state, so
deploying it is a matter of pointing a host at this repository. What follows is
the honest state of the free options as of early 2026, because most guides you
will find are out of date.

## What it actually needs

Measured on the Dragon position at depth 14, single thread:

| Mode | Resident memory | What you lose |
| --- | --- | --- |
| Default (two engine processes) | ~675 MB | nothing |
| `DECODEX_LEAN=1` (one process) | ~310 MB | the NNUE piece-importance panel |

The second Stockfish process exists only to answer `eval`, the non-standard
command that produces the per-piece ablation table. Everything else — candidate
moves, threats, purpose, tactics, roles, concepts, game review — comes from the
search engine and works identically in lean mode.

Analysis is CPU-bound. Measured inside a container capped at Render's free
allowance (`--memory 512m --cpus 0.1`), with the lowered ceilings that
`render.yaml` sets:

| Request | Time |
| --- | --- |
| Position, depth 14, one side | ~5 s |
| Game review, 28 half-moves, depth 10 | ~17 s |
| Memory used | 218 MB of 512 MB |

Slow but usable. On a full core the same requests take well under a second.

## Free options, ranked by how well they actually work

### Render free — works, sleeps

512 MB RAM, 0.1 vCPU, no credit card. Fits in lean mode with room to spare.
`render.yaml` is already configured for it.

1. Push this repo to your GitHub account.
2. On <https://render.com>, **New → Blueprint**, select the repo.
3. Render reads `render.yaml` and deploys. First build takes ~10 minutes, mostly
   compiling Stockfish.

The catch, stated plainly: free services **sleep after 15 minutes idle**, and
waking takes around 50 seconds because the NNUE network reloads. A visitor
arriving cold will think the site is broken. Upgrading to `starter` ($7/month)
removes the sleep; nothing else changes.

You can paper over it with an external pinger (cron-job.org, every 10 minutes),
which keeps the container warm within the 750 monthly instance-hours. That is
750 hours against 730 in a month, so a single always-on service just fits.

### Google Cloud Run — generous, but cold starts

180,000 vCPU-seconds and 360,000 GiB-seconds free per month, which is a lot of
analysis. Scales to zero, so the same cold-start problem, but you can set
`--min-instances=1` and it will still be free-ish within the allowance. Requires
a credit card and more setup than Render.

```bash
gcloud run deploy decodex --source . --region europe-west1 \
  --allow-unauthenticated --memory 1Gi --cpu 1 --min-instances 1
```

### Oracle Cloud Always Free — genuinely always-on, most work

4 ARM OCPUs and 24 GB RAM, free forever, no sleep. Comfortably the most capable
free option, and the only one where you would not need lean mode. The cost is
that you are administering a VM: install Docker, run the container, put a
reverse proxy in front, get a TLS certificate. Note the Dockerfile builds
Stockfish with `ARCH=x86-64`; on Oracle's ARM instances change that to
`ARCH=armv8`.

### Not free any more, whatever the guides say

- **Fly.io** removed its free tier in 2024. New accounts pay from the first
  machine. `fly.toml` is kept because the config is still correct if you are
  paying, but do not expect it to be free.
- **Heroku** has had no free tier since November 2022.
- **Hugging Face Spaces** free CPU tier no longer covers Docker Spaces; that now
  needs PRO. Static Spaces remain free.

## The option that is free forever with no host at all

Stockfish compiles to WebAssembly — lichess runs exactly that in the browser.
If the engine and the fact extraction both ran client-side, this becomes a
folder of static files that GitHub Pages will host for nothing, permanently, with
no sleep, no rate limits and no shared CPU. Each visitor supplies their own
compute, so it also scales without limit.

That means porting the fact layers from Python to JavaScript. The static ones
(`motifs`, `roles`, `concepts`, `values`, `assess`) are pure functions over a
board and would translate fairly directly against `chess.js`. Two caveats worth
knowing before choosing this path:

- Multi-threaded WASM needs `SharedArrayBuffer`, which needs COOP and COEP
  headers. GitHub Pages does not send them, so the engine would run
  single-threaded and therefore slower per visitor.
- The NNUE ablation table depends on Stockfish's `eval` output, which the WASM
  builds do not expose the same way. That panel would likely be lost, as it is
  in lean mode.

It is the architecturally correct answer to "free and always on", and it is a
real rewrite rather than a configuration change. Ask if you want it.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | 8000 | Port to bind |
| `DECODEX_ENGINE` | `stockfish` on `PATH` | Path to the UCI engine |
| `DECODEX_LEAN` | off | Single engine process; drops the NNUE panel |
| `DECODEX_MAX_POSITION_DEPTH` | 18 | Depth ceiling for a position |
| `DECODEX_MAX_GAME_DEPTH` | 12 | Depth ceiling for a game review |
| `DECODEX_MAX_PLIES` | 160 | Longest game accepted |

## Checking a deployment

```bash
curl https://your-host/healthz          # {"status":"ok"}
curl https://your-host/api/limits       # ceilings, engine name, lean flag
```

If `/healthz` answers but analysis times out, the host is CPU-starved: lower
`DECODEX_MAX_POSITION_DEPTH`.
