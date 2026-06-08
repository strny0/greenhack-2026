#!/usr/bin/env bash
# Container entrypoint for Grid Pulse.
#
# 1. Generate /app/backend/.env from the container environment, defaulting every
#    knob so anything not supplied via docker-compose still has a sane value.
#    (app.config also reads os.environ directly, so values passed straight
#    through compose `environment:` are honoured even beyond what is listed here.)
# 2. Prepare the heavy bits ONCE into the mounted volumes (idempotent — skipped
#    when already present, so they survive image updates and are not re-fetched):
#      • download the ČEPS dataset into $GRID_DATA_DIR
#      • build the gridstats bundle into $GRIDSTATS_TARGET_DIR
# 3. Launch the single process: uvicorn serves /api AND the built frontend at /.
set -euo pipefail

cd /app/backend

DATA_DIR="${GRID_DATA_DIR:-/data/dataset/data}"
TARGET_DIR="${GRIDSTATS_TARGET_DIR:-/data/gridstats/target}"
TRACE_FILE="${GRID_CHAT_TRACE_FILE:-/data/traces/chat_traces.jsonl}"

# --- 1. .env (mirrors src/backend/.env.example, for inspectability) -----------
cat > .env <<EOF
# Generated at container start from the environment — edit via docker-compose.
# --- AI / dispatcher chatbot (OpenAI-compatible; empty key => grounded context only) ---
AI_BASE_URL=${AI_BASE_URL:-https://openrouter.ai/api/v1}
AI_API_KEY=${AI_API_KEY:-${OPENROUTER_API_KEY:-}}
AI_MODEL=${AI_MODEL:-anthropic/claude-sonnet-4.5}

# --- Data locations (volume-mounted; overrides ship in the image) ---
GRID_DATA_DIR=${DATA_DIR}
GRID_OVERRIDES_DIR=${GRID_OVERRIDES_DIR:-/app/dataset/overrides}
GRIDSTATS_TARGET_DIR=${TARGET_DIR}

# --- Frame preload window (startup warmup) ---
GRID_PRELOAD_START=${GRID_PRELOAD_START:-0}
GRID_PRELOAD_FRAMES=${GRID_PRELOAD_FRAMES:-48}
GRID_FRAME_CACHE_SIZE=${GRID_FRAME_CACHE_SIZE:-800}

# --- Alert thresholds ---
GRID_LINE_LOADING_WARN=${GRID_LINE_LOADING_WARN:-75}
GRID_LINE_LOADING_ALERT=${GRID_LINE_LOADING_ALERT:-90}
GRID_VOLTAGE_WARN_MARGIN=${GRID_VOLTAGE_WARN_MARGIN:-0.01}

# --- N-1 security analysis ---
GRID_N1_OVERLOAD_PCT=${GRID_N1_OVERLOAD_PCT:-100}
GRID_N1_MAX_CONTINGENCIES=${GRID_N1_MAX_CONTINGENCIES:-200}

# --- Forecast-vs-actual deviation triage ---
GRID_DEV_SOLAR_MW=${GRID_DEV_SOLAR_MW:-300}
GRID_DEV_WIND_MW=${GRID_DEV_WIND_MW:-40}
GRID_N1_DEV_LIMIT=${GRID_N1_DEV_LIMIT:-20}
GRID_DEV_SLACK_LOAD_FRACTION=${GRID_DEV_SLACK_LOAD_FRACTION:-0.25}

# --- Chat usage tracing (persisted on the mounted volume) ---
GRID_CHAT_TRACING=${GRID_CHAT_TRACING:-1}
GRID_CHAT_TRACE_FILE=${TRACE_FILE}
GRID_ADMIN_TOKEN=${GRID_ADMIN_TOKEN:-}
EOF

mkdir -p "$(dirname "$TRACE_FILE")"

# --- 2a. dataset (downloaded once into the mounted volume) --------------------
if [ -d "$DATA_DIR/snapshots" ]; then
    echo "[entrypoint] dataset present at $DATA_DIR"
else
    url="${DATASET_URL:-https://cloud.jastr.dev/public.php/dav/files/greenhack-2026-data}"
    echo "[entrypoint] dataset not found — downloading once into $DATA_DIR (this can take a while)…"
    tmp_zip="$(mktemp)"
    tmp_dir="$(mktemp -d)"
    curl -L --fail -o "$tmp_zip" "$url"
    unzip -q "$tmp_zip" -d "$tmp_dir"
    inner="$(find "$tmp_dir" -mindepth 1 -maxdepth 1 -type d | head -n1)"
    mkdir -p "$(dirname "$DATA_DIR")"
    rm -rf "$DATA_DIR"
    mv "$inner/data" "$DATA_DIR"
    rm -rf "$tmp_zip" "$tmp_dir"
    echo "[entrypoint] dataset ready at $DATA_DIR"
fi

# --- 2b. gridstats bundle (built once into the mounted volume) ----------------
if [ -f "$TARGET_DIR/metrics.parquet" ]; then
    echo "[entrypoint] gridstats bundle present at $TARGET_DIR"
else
    echo "[entrypoint] gridstats bundle not found — building once (scans all snapshots)…"
    mkdir -p "$TARGET_DIR"
    python -m app.gridstats.build
    rm -rf "$TARGET_DIR/cache"
    echo "[entrypoint] gridstats bundle ready at $TARGET_DIR"
fi

# --- 3. launch ----------------------------------------------------------------
echo "[entrypoint] Grid Pulse on :${PORT:-8099}  (data=$DATA_DIR, bundle=$TARGET_DIR, traces=$TRACE_FILE)"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8099}"
