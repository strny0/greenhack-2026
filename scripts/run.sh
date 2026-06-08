#!/usr/bin/env bash
# Reproducible local launch for Grid Pulse (dev mode).
#
# One command that:
#   1. checks the dataset is present (points you to download_dataset.sh if not),
#   2. checks/install backend deps (uv preferred, falls back to python3.12 + pip),
#   3. validates backend/.env (creates it from .env.example on first run),
#   4. checks/install frontend deps (npm),
#   5. starts the backend (uvicorn :8099) and the frontend (vite :5173).
#
# Open http://127.0.0.1:5173  (Vite proxies /api to the backend).
# Ctrl-C stops both processes.
#
# Env overrides:  PORT (backend, default 8099)   SKIP_INSTALL=1 (skip dep checks)
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
BACKEND="$REPO_ROOT/src/backend"
FRONTEND="$REPO_ROOT/src/frontend"
VENV="$BACKEND/.venv"
PORT="${PORT:-8099}"

cyan()  { printf '\033[36m==> %s\033[0m\n' "$*"; }
green() { printf '\033[32m    %s\033[0m\n' "$*"; }
red()   { printf '\033[31m!!  %s\033[0m\n' "$*" >&2; }

missing=()

# --- 1. dataset --------------------------------------------------------------
if [ ! -d "$REPO_ROOT/dataset/data/snapshots" ]; then
    red "Dataset not found at dataset/data/snapshots"
    red "Download it first:  ./scripts/download_dataset.sh"
    exit 1
fi
green "dataset present (dataset/data)"

# --- 2. backend tooling ------------------------------------------------------
have() { command -v "$1" &>/dev/null; }

if have uv; then
    PY_TOOL="uv"
elif have python3.12; then
    PY_TOOL="python3.12"
elif have python3; then
    PY_TOOL="python3"
else
    missing+=("Python 3.12 (install python3.12, or 'uv' from https://docs.astral.sh/uv/)")
    PY_TOOL=""
fi

if ! have node || ! have npm; then
    missing+=("Node.js + npm (https://nodejs.org/)")
fi

if [ "${#missing[@]}" -gt 0 ]; then
    red "Missing dependencies:"
    for m in "${missing[@]}"; do red "  - $m"; done
    exit 1
fi

# --- 3. backend venv + deps --------------------------------------------------
if [ "${SKIP_INSTALL:-0}" != "1" ]; then
    if [ ! -x "$VENV/bin/python" ]; then
        cyan "creating backend venv ($PY_TOOL)"
        if [ "$PY_TOOL" = "uv" ]; then
            uv venv --python 3.12 "$VENV"
        else
            "$PY_TOOL" -m venv "$VENV"
        fi
    fi
    # (re)install deps only when requirements.txt changed since last install
    if [ ! -f "$VENV/.deps-stamp" ] || [ "$BACKEND/requirements.txt" -nt "$VENV/.deps-stamp" ]; then
        cyan "installing backend deps"
        if [ "$PY_TOOL" = "uv" ]; then
            uv pip install --python "$VENV/bin/python" -r "$BACKEND/requirements.txt"
        else
            "$VENV/bin/python" -m pip install --quiet --upgrade pip
            "$VENV/bin/python" -m pip install -r "$BACKEND/requirements.txt"
        fi
        touch "$VENV/.deps-stamp"
    else
        green "backend deps up to date"
    fi
fi

# --- 4. backend .env ---------------------------------------------------------
if [ ! -f "$BACKEND/.env" ]; then
    cyan "creating backend/.env from .env.example"
    cp "$BACKEND/.env.example" "$BACKEND/.env"
    green "edit src/backend/.env and set AI_API_KEY to enable the dispatcher chatbot"
    green "(the app runs fine without it; the chat just returns its grounded context)"
else
    green "backend/.env present"
fi

# --- 5. gridstats bundle (built once via `python -m app.gridstats.build`) -----
# Precomputed historical/statistical bundle the dispatcher agent serves from.
# The build scans all 8760 snapshots, so do it once; presence of metrics.parquet
# (what the runtime loader checks) means it's already built.
GRIDSTATS_BUNDLE="$BACKEND/app/gridstats/target/metrics.parquet"
if [ ! -f "$GRIDSTATS_BUNDLE" ]; then
    cyan "building gridstats bundle (one-time; scans all snapshots — may take a few minutes)"
    ( cd "$BACKEND" && "$VENV/bin/python" -m app.gridstats.build )
else
    green "gridstats bundle present"
fi

# --- 6. frontend deps --------------------------------------------------------
if [ "${SKIP_INSTALL:-0}" != "1" ]; then
    if [ ! -d "$FRONTEND/node_modules" ] || [ "$FRONTEND/package-lock.json" -nt "$FRONTEND/node_modules" ]; then
        cyan "installing frontend deps (npm install)"
        (cd "$FRONTEND" && npm install)
    else
        green "frontend deps up to date"
    fi
fi

# --- 7. launch both ----------------------------------------------------------
pids=()
cleanup() {
    cyan "stopping..."
    for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
    wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cyan "starting backend  (uvicorn :$PORT)"
( cd "$BACKEND" && exec "$VENV/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" ) &
pids+=($!)

cyan "starting frontend (vite :5173)"
( cd "$FRONTEND" && exec npm run dev ) &
pids+=($!)

green "open  http://127.0.0.1:5173   (Ctrl-C to stop)"

# Exit (and trigger cleanup) as soon as either process dies.
wait -n
