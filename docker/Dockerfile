# syntax=docker/dockerfile:1
#
# Grid Pulse — lean image; one uvicorn process serves the API (/api/*) and the
# built frontend (/). The image contains ONLY code + deps + the built UI + the
# small, version-controlled operator overrides.
#
# The large bits are prepared ONCE at first container start (see entrypoint.sh)
# into mounted volumes, so they survive image updates and are never re-fetched:
#   • the ČEPS dataset  -> downloaded into the dataset volume
#   • the gridstats bundle (`python -m app.gridstats.build`) -> built into the
#     gridstats volume
#
# Build context MUST be the repo root:
#   docker build -f docker/Dockerfile -t gridpulse .
# or via the compose files in this directory.

# ---------------------------------------------------------------------------
# Stage 1 — build the frontend to a static bundle (dist/)
# ---------------------------------------------------------------------------
FROM node:20-slim AS frontend
WORKDIR /build
# Install deps first (cached unless the lockfile changes).
COPY src/frontend/package.json src/frontend/package-lock.json ./
RUN npm ci
COPY src/frontend/ ./
RUN npm run build        # -> /build/dist


# ---------------------------------------------------------------------------
# Stage 2 — runtime: backend + deps + frontend (dataset/bundle come at runtime)
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# System deps: curl+unzip (runtime dataset download + healthcheck), libgomp1 (numba).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl unzip ca-certificates libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# Defaults point at the volume mounts; override any of them via compose env.
# Only GRID_OVERRIDES_DIR stays inside the image (small, version-controlled).
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8099 \
    DATASET_URL=https://cloud.jastr.dev/public.php/dav/files/greenhack-2026-data \
    GRID_DATA_DIR=/data/dataset/data \
    GRID_OVERRIDES_DIR=/app/dataset/overrides \
    GRIDSTATS_TARGET_DIR=/data/gridstats/target \
    GRID_CHAT_TRACE_FILE=/data/traces/chat_traces.jsonl

WORKDIR /app/backend

# Python dependencies (the container IS the isolation; no venv needed).
COPY src/backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# Backend source + version-controlled operator overrides (stay in the image).
COPY src/backend/       /app/backend/
COPY dataset/overrides/ /app/dataset/overrides/

# Built frontend from stage 1 (served by uvicorn at "/", see app/main.py).
COPY --from=frontend /build/dist /app/frontend/dist

# Entrypoint: prepare dataset + gridstats bundle in volumes (once), write .env, run.
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8099
# Generous start-period: the FIRST run downloads the dataset and builds the
# bundle before uvicorn starts. Subsequent starts (warm volumes) are quick.
HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=5 \
  CMD curl -fsS "http://127.0.0.1:${PORT:-8099}/api/health" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
