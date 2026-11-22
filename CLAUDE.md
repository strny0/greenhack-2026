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
- To use an Anthropic key directly: `AI_BASE_URL=https://api.anthropic.com/v1/`
  and `AI_MODEL=claude-sonnet-5-5`. No temperature is sent unless
  `AI_TEMPERATURE` is set, because Claude Sonnet 5+ rejects it. An
  `api.anthropic.com` base URL makes the agent use the native Anthropic API
  (Pydantic AI `AnthropicModel`) with prompt caching; other URLs use the
  OpenAI-compatible model, which gets no caching.
- Agent prompts go in `instructions` / `@agent.instructions`, never
  `system_prompt`: Pydantic AI drops system prompts on runs that pass
  `message_history`, which every follow-up chat turn does.

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
