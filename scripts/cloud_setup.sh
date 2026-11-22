#!/usr/bin/env bash
# Non-interactive, idempotent dev setup (used for Claude Code cloud sessions,
# also fine locally). Installs backend + frontend deps, fetches the dataset if
# missing, and builds the gridstats bundle once. Does NOT start servers; use
# scripts/run.sh (SKIP_INSTALL=1) for that.
#
# The dataset host (cloud.jastr.dev) must be reachable. In Claude Code cloud,
# use the "greenhack-2026" environment, which allows it.
set -euo pipefail

REPO_ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
BACKEND="$REPO_ROOT/src/backend"
FRONTEND="$REPO_ROOT/src/frontend"
VENV="$BACKEND/.venv"

# Backend (Python 3.12 via uv)
[ -x "$VENV/bin/python" ] || uv venv --python 3.12 "$VENV"
uv pip install --python "$VENV/bin/python" -r "$BACKEND/requirements.txt"
touch "$VENV/.deps-stamp"
[ -f "$BACKEND/.env" ] || cp "$BACKEND/.env.example" "$BACKEND/.env"

# Frontend
(cd "$FRONTEND" && npm ci --no-audit --no-fund)

# Dataset (gitignored, ~8760 hourly snapshots)
if [ ! -d "$REPO_ROOT/dataset/data/snapshots" ]; then
    "$REPO_ROOT/scripts/download_dataset.sh" || {
        echo "Dataset download failed (is cloud.jastr.dev allowed by the network policy?)" >&2
        exit 0
    }
fi

# gridstats bundle (one-time scan of all snapshots)
if [ ! -f "$BACKEND/app/gridstats/target/metrics.parquet" ]; then
    (cd "$BACKEND" && "$VENV/bin/python" -m app.gridstats.build)
fi
echo "Setup done."
