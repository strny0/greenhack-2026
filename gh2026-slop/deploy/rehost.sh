#!/usr/bin/env bash
# Rehost Grid Pulse on pc-praha after changes.
#
#   git pull && rebuild frontend (only if deps changed) && restart uvicorn
#
# Usage (from anywhere on pc-praha):
#   ~/Projects/greenhack-2026/gh2026-slop/deploy/rehost.sh
#
# Override defaults via env:
#   HOST=0.0.0.0 PORT=8099 NO_PULL=1 ./rehost.sh
set -euo pipefail

# --- paths -------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$(cd "$SCRIPT_DIR/.." && pwd)"          # .../gh2026-slop
BACKEND="$APP/backend"
FRONTEND="$APP/frontend"
VENV="$BACKEND/.venv"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8099}"
LOG="$BACKEND/uvicorn.log"

cyan() { printf '\033[36m==> %s\033[0m\n' "$*"; }

# --- 1. pull -----------------------------------------------------------------
if [ "${NO_PULL:-0}" != "1" ]; then
  cyan "git pull"
  git -C "$APP" pull --ff-only
fi

# --- 2. backend deps (only when requirements change) -------------------------
if [ ! -x "$VENV/bin/python" ]; then
  cyan "creating venv"
  python3.12 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r "$BACKEND/requirements.txt"
  touch "$VENV/.deps-stamp"
elif [ "$BACKEND/requirements.txt" -nt "$VENV/.deps-stamp" ]; then
  cyan "requirements changed — reinstalling backend deps"
  "$VENV/bin/pip" install -q -r "$BACKEND/requirements.txt"
  touch "$VENV/.deps-stamp"
else
  cyan "backend deps up to date"
fi

# --- 3. frontend build (npm ci only when the lockfile changes) ---------------
cd "$FRONTEND"
if [ ! -d node_modules ] || [ package-lock.json -nt node_modules ]; then
  cyan "installing frontend deps (npm ci)"
  npm ci
fi
cyan "building frontend"
npm run build

# --- 4. restart uvicorn ------------------------------------------------------
cyan "stopping old backend (if any)"
pids="$(pgrep -f 'uvicorn app.main:app' || true)"
if [ -n "$pids" ]; then
  kill $pids 2>/dev/null || true
  sleep 1
  kill -9 $pids 2>/dev/null || true
fi

cyan "starting uvicorn on $HOST:$PORT"
cd "$BACKEND"
nohup "$VENV/bin/python" -m uvicorn app.main:app --host "$HOST" --port "$PORT" \
  > "$LOG" 2>&1 &
disown || true

# --- 5. health check ---------------------------------------------------------
cyan "waiting for /api/health ..."
for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    printf '\033[32m    healthy ✔  http://%s:%s  (logs: %s)\033[0m\n' "$HOST" "$PORT" "$LOG"
    exit 0
  fi
  sleep 1
done

printf '\033[31m    !! not healthy after 40s — last log lines:\033[0m\n' >&2
tail -n 25 "$LOG" >&2 || true
exit 1
