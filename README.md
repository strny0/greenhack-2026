# Grid Pulse — real-time decision support for transmission grids

**ČEPS · GreenHack 2026 — Grid Pulse Challenge.**

An AI-assisted, map-based view of the power transmission grid that turns raw
load-flow data into clear, timely operational insight for control-room
dispatchers. The goal of the challenge is to make the grid **visible**,
**understandable**, and **predictable**, converting abundant data into
actionable situational awareness while operators work under time pressure.

> See [`docs/Grid Pulse Challenge.pdf`](docs/Grid%20Pulse%20Challenge.pdf) for
> the full challenge brief.

The working application lives in **[`gh2026-slop/`](gh2026-slop/)**.

---

## What it does

- **Map-based grid view**: 118 substations and 186 branches (lines +
  transformers) on a live map of California. Lines coloured by loading
  (green → amber → red), nodes typed by role (generation / load / substation /
  slack) and sized by power.
- **Real load flow**: AC power flow ([pandapower](https://www.pandapower.org/))
  solved on demand for any hour of 2024 (8760 hourly snapshots).
- **Detail panels**: click any node or line for static ratings, live values,
  and a windowed time-series chart.
- **Threshold alerts**: line overloads and voltages against each bus's rated band.
- **Time scrubber / "pulse"**: play through the hourly window; the map and KPIs
  animate as a living system state.
- **What-if scenarios**: disconnect a line / scale load, re-solve, and see which
  branches move (and which overload) versus the base case. Simulate a dire disaster.
- **N-1 security analysis**: trip each line, re-solve, and rank the worst
  contingencies; non-converging trips are flagged as islanding / voltage collapse.
- **Dispatcher chatbot**: natural-language, tool-calling agent grounded in the
  live grid state, via any OpenAI-compatible endpoint (OpenRouter by default).

---

## Repository layout

| Path | What it is |
|------|------------|
| [`gh2026-slop/`](gh2026-slop/) | **The application** — FastAPI + pandapower backend and a React / TypeScript / MapLibre frontend. See its [README](gh2026-slop/README.md). |
| [`dataset/`](dataset/) | The ČEPS IEEE-118 dataset (8760 hourly pandapower snapshots, static network, forecasts, realtime feed) and its [schema docs](dataset/README.md). The `data/` payload is gitignored. |
| [`docs/`](docs/) | Challenge brief (`Grid Pulse Challenge.pdf`), the source `NREL_IEEE_118.pdf`, and `dataset_schema.md`. |
| [`scripts/`](scripts/) | Helpers to download the dataset (`download_dataset.sh` / `.ps1`) and a quick `analyze_datasets.py`. |
| [`src/case_study/`](src/case_study/) | Early data-exploration / loader prototype that fed the final design. |

---

## Architecture

```
ČEPS dataset (pandapower JSON snapshots + static CSV + forecasts)
        │
   backend/  Python · FastAPI · pandapower · grid engine + AI agent
        │     load flow · N-1 · what-if · weather · chat
        │     canonical model: Node / Line / StateFrame
        ▼
   /api (REST)   ──proxied──▶   frontend/  React · TypeScript · Vite · MapLibre GL
```

The backend is the only component that touches physics or the dataset; the
frontend only ever sees the canonical `Node / Line / StateFrame` model.

**Engine note:** the dataset is native pandapower (`pandapowerNet` JSON,
IEEE-118-derived), so snapshots load with one call (`pp.from_json`), generators
are preserved, and N-1 / what-if run natively. See
[`gh2026-slop/README.md`](gh2026-slop/README.md) and `gh2026-slop/deliverables.txt`
for the full rationale.

---

## Quickstart

### 1. Data

Download the dataset into `dataset/data/` (or set `GRID_DATA_DIR` to the inner
`data/` directory):

```bash
./scripts/download_dataset.sh        # or scripts/download_dataset.ps1 on Windows
```

The backend expects `data/.../data/{snapshots,static,forecasts,realtime}`.

### 2. Backend (Python 3.12)

```bash
cd gh2026-slop/backend
uv venv --python 3.12 .venv          # or: python3.12 -m venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt   # or: pip install -r requirements.txt
./run.sh                             # http://127.0.0.1:8099
```

### 3. Frontend

```bash
cd gh2026-slop/frontend
npm install
npm run dev                          # http://127.0.0.1:5173
```

Vite proxies `/api` to the backend, so just open **http://127.0.0.1:5173**.

### 4. Chatbot (optional)

```bash
cp gh2026-slop/backend/.env.example gh2026-slop/backend/.env
# set AI_API_KEY (OpenAI-compatible, e.g. OpenRouter):
#   AI_BASE_URL=https://openrouter.ai/api/v1
#   AI_MODEL=anthropic/claude-sonnet-4.5
```

Without a key the chatbot still returns the grounded grid context, so you can
see exactly what the model would be given.

---

## API at a glance

All endpoints are under `/api` (backend on `:8099`). Full `curl` tests for each
are in [`gh2026-slop/deliverables.txt`](gh2026-slop/deliverables.txt).

| Endpoint | Purpose |
|----------|---------|
| `GET /api/health` | liveness + snapshot count |
| `GET /api/meta` | timestamps, bbox, thresholds, suggested questions |
| `GET /api/frame?timestamp=…` | canonical state (nodes + lines + summary) for one hour |
| `GET /api/alerts?timestamp=…` | threshold alerts (loading + voltage) |
| `GET /api/timeseries?…` | one element's metric across a window |
| `GET /api/n1?timestamp=…` | N-1 contingency ranking |
| `POST /api/whatif` | disconnect lines / scale load, diff vs base |
| `GET /api/weather` | cloud cover / wind + solar-drop heuristic |
| `POST /api/agent/stream` | tool-calling dispatcher agent (NDJSON stream) |

---

The dataset is derived from
[evgenytsydenov/ieee118_power_flow_data](https://github.com/evgenytsydenov/ieee118_power_flow_data)
and licensed **[CC-BY-NC-SA 4.0](http://creativecommons.org/licenses/by-nc-sa/4.0/)**
(non-commercial; derivatives under the same licence).
