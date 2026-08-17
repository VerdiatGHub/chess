# Stockfish is compiled from source rather than taken from a release tarball,
# because the official builds target specific instruction sets (avx2, bmi2) and
# a host without them dies with SIGILL. `build ARCH=x86-64` picks a baseline
# that runs anywhere, at some cost in speed.
FROM debian:bookworm-slim AS engine

ARG STOCKFISH_VERSION=sf_17.1

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone --depth 1 --branch ${STOCKFISH_VERSION} \
      https://github.com/official-stockfish/Stockfish.git
WORKDIR /build/Stockfish/src
# `make net` fetches the NNUE network, which the Makefile needs curl or wget for
# and then embeds into the binary. Plain `build` rather than `profile-build`:
# PGO gains perhaps 10% at runtime but doubles an already slow compile.
RUN make -j"$(nproc)" net && make -j"$(nproc)" build ARCH=x86-64 && strip stockfish


FROM python:3.12-slim-bookworm

# Never run the service as root: a public endpoint should not have write access
# to its own code.
RUN useradd --create-home --shell /usr/sbin/nologin decodex

COPY --from=engine /build/Stockfish/src/stockfish /usr/local/bin/stockfish

WORKDIR /app
COPY pyproject.toml README.md ./
COPY decodex ./decodex
# COPY preserves the source permissions, and a checkout that is group-only
# readable would leave the unprivileged runtime user unable to import its own
# code. Normalise before installing rather than trusting the build host's umask.
RUN chmod -R a+rX /app \
    && pip install --no-cache-dir ".[web]" \
    && chmod -R a+rX /usr/local/lib/python3.12/site-packages/decodex

USER decodex

ENV DECODEX_ENGINE=/usr/local/bin/stockfish \
    PORT=8000 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['PORT']}/healthz\", timeout=4).status == 200 else 1)"

# One worker by design. The engine is a single shared process behind a lock, so
# extra workers would each spawn their own Stockfish and contend for the same
# cores. Scale by adding machines, not workers.
CMD ["sh", "-c", "exec uvicorn decodex.web:create_app --factory --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips '*'"]
