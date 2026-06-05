# Case Study — Work Done & Handoff

## Goal

Build a standalone Python data analysis layer in `src/case_study/` that:

1. Loads grid snapshots, DA forecasts, and realtime CSVs from the NREL-118 dataset
2. Computes a `GridStats` harness (STL decomposition + branch percentile table) over all 8760 hours of 2024
3. Exposes `explain_hour(timestamp, gs)` → structured dict for LLM context injection
4. Exposes `find_interesting_days(gs)` → ranked DataFrame of anomalous calendar days
5. Later: these same functions become tool calls for the LLM chatbot

## Key Context

- **Dataset**: NREL-118 bus system, 3 regions mapping to **California** utilities:
  - r1 (42 buses) = Bay Area, PG&E
  - r2 (48 buses) = Sacramento, SMUD
  - r3 (28 buses) = San Diego, SDG&E
  - Source: `docs/NREL_IEEE_118.pdf` pp. 1–5
- **Not Czech** — the backend projects onto Czech bounds for the hackathon UI, but geographic reality is California
- **Geo projection**: `geo.py` uses California lon/lat bounds (-124.5→-114.5, 32.5→42.0). The y-axis is **not** inverted (unlike the backend's Czech version) — confirmed by checking that r1 (Bay Area) has the highest (least-negative) y values in `buses.csv`
- **Backend** (`gh2026-slop/backend/app/`) is NOT modified — it stays as a FastAPI service with Czech projection
- **Data dir**: `dataset/data/` at workspace root (overriding the backend's default path)

## Files

| File | Status | Notes |
|------|--------|-------|
| `config.py` | ✅ done | California bounds, no dotenv, no env vars |
| `geo.py` | ✅ done | `GeoProjector`, y-axis orientation fixed vs backend |
| `loader.py` | ✅ done | `DataStore.scan_all()`, `ForecastStore`, `RealtimeStore` |
| `analysis.py` | ✅ written | Smoke test in progress — see Open Items |
| `pyproject.toml` | ✅ done | Python 3.12, pandapower 2.14.10 + statsmodels |
| `.venv/` | ✅ created | `uv venv --python 3.12` + `uv pip install -r pyproject.toml` |

## Running

```bash
# always run from src/ so relative package imports resolve
cd /home/jstrnad/source/greenhack/src

# fast smoke test (~30 sec) — verifies all three stores load correctly
../src/case_study/.venv/bin/python -m case_study.loader

# full analysis build (~5–10 min) — scans all 8760 snapshots, builds GridStats
../src/case_study/.venv/bin/python -m case_study.analysis
```

## Architecture

### `DataStore.scan_all() -> (metrics_df, branch_df)`

Single pass over all 8760 snapshots. Returns:
- `metrics_df` — system-level metrics per hour: `total_load_mw`, `total_gen_mw`, `slack_mw`, `max_line_loading_pct`, `n_overloaded_lines`, `converged`
- `branch_df` — per-branch loading percentages per hour (186 branch columns)

Both indexed by datetime. Previously `all_metrics_df()` and `_build_branch_pcts()` were separate passes (2× slower); now combined.

### `ForecastStore.system_forecast() -> DataFrame`

Loads all DA forecast CSVs (3 regional load + 75 solar + 17 wind) and returns a single aligned DataFrame with columns: `load_r1_mw`, `load_r2_mw`, `load_r3_mw`, `load_total_mw`, `solar_mw`, `wind_mw`.

### `RealtimeStore.system_totals() -> DataFrame`

Loads `gens_ts.csv` and `loads_ts.csv`, aggregates by hour. Splits generation by name prefix (`solar_*`, `wind_*`). Columns: `load_mw`, `solar_mw`, `wind_mw`, `other_gen_mw`, `gen_total_mw`.

### `GridStats` (in `analysis.py`)

Built once from all three stores:
1. **STL decomposition** of 5 system series (load, max_loading, solar, wind, slack) with `period=24, robust=True` — produces residuals that are the anomaly signal
2. **Branch percentile table** — p90/p95/p99 per `(hour_of_day, is_workday)` stratum, built from `branch_df` without any extra file reads
3. **Forecast error baselines** — MAE + std per metric

### `explain_hour(timestamp, gs, ds=None) -> dict`

Produces the LLM harness dict for a specific hour:
- z-scores for all 5 system metrics (from STL residuals / residual_std)
- forecast deltas (actual − forecast for solar/wind/load)
- momentum (load and loading deltas at 1h and 24h lags)
- stressed branches above their p90 threshold — **requires `ds` (DataStore) to be passed** to read actual branch loadings from the snapshot

`summary_text` field is ~150 tokens of human-readable text, ready for LLM context injection.

### `find_interesting_days(gs, n=20) -> DataFrame`

Scores each calendar day by:
- `composite_z` — mean |z-score| across all 5 system metrics
- `max_branch_stress_pct` — peak max_line_loading_pct that day
- `forecast_error_mw` — mean absolute forecast error (solar + wind + load)
- `n_alert_hours` — hours with max_line_loading ≥ 90%

Returns top-n days sorted by `composite_z`.

## Open Items

1. **Smoke test**: `analysis.py` smoke test may still be running — verify it completes and check output
2. **`_build_branch_pcts_from_df` index**: after `set_index(["hour", "is_workday"])` the datetime index is dropped; verify groupby produces the expected `(hour, is_workday)` MultiIndex
3. **Pick the pitch day**: once `find_interesting_days()` output is in hand, inspect top candidates and pick one with a good narrative (near-miss overload, big renewable surprise, or both)
4. **Next phase**: implement the LLM tool call layer — each of `explain_hour`, `find_interesting_days`, and per-element timeseries queries becomes an agent tool definition

## Relevant Docs Read

- `docs/NREL_IEEE_118.pdf` pp. 1–5 — California regions, system characteristics
- `docs/dataset_schema.md` — column stats for all CSVs
- `dataset/convention.md` — naming conventions
- `dataset/data/static/buses.csv` — 118 buses, regions, voltage levels, coordinates
- `gh2026-slop/backend/app/data_loader.py`, `engine.py`, `model.py`, `config.py`, `geo.py` — all read in full
