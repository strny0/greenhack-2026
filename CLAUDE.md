# Smooth Operator (Grid Pulse): notes for Claude

FastAPI + pandapower backend (`src/backend`, Python 3.12) and React/Vite
frontend (`src/frontend`, Node 22). See README.md for the full picture.

## Setup

```bash
./scripts/cloud_setup.sh        # deps, dataset download, gridstats bundle (idempotent)
SKIP_INSTALL=1 ./scripts/run.sh # backend :8099 + vite :5173 (proxies /api)
```

- The dataset is gitignored and comes from `cloud.jastr.dev`. Claude Code cloud
  sessions need the personal **greenhack-2026** cloud environment (allows that
  host); the built-in environment blocks it with a proxy 403.
- `uv` is the Python tool. The venv lives at `src/backend/.venv`.
- Chatbot needs `AI_API_KEY` in `src/backend/.env` (OpenAI-compatible, OpenRouter
  by default). Without it the app runs and chat returns grounded context only.
  A key needs `openrouter.ai` reachable too.

## Tests

```bash
cd src/backend && .venv/bin/python -m pytest -q   # needs dataset for app/tests/*
cd src/frontend && npm test && npm run build
```

Without the dataset, only `app/gridstats` (fixture-based) and
`app/tests/test_whatif_stack.py` can run; the other `app/tests/*` modules fail
at collection with "Snapshots dir not found".

## Gotchas

- `numpy` is pinned to 1.26.4 (numba/pandapower), so `pyarrow` must stay `<26`
  (26+ requires NumPy 2 and breaks every parquet read).
