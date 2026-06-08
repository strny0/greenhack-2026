#!/usr/bin/env bash
# Launch the Grid Pulse backend.
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate
exec python -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8099}" "$@"
