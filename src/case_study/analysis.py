"""Statistical harness for grid case-study analysis.

GridStats   — pre-computed STL decomposition + branch percentile table
explain_hour — produces the LLM context dict for a specific timestamp
find_interesting_days — ranks all 365 calendar days by anomaly composite score
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL

from . import config
from .loader import DataStore, ForecastStore, RealtimeStore

# (metric, forecast column, realtime column) — the three day-ahead vs actual pairs
_SURPRISE_PAIRS = [
    ("load",  "load_total_mw", "load_mw"),
    ("solar", "solar_mw",      "solar_mw"),
    ("wind",  "wind_mw",       "wind_mw"),
]


# ---------------------------------------------------------------------------
# GridStats
# ---------------------------------------------------------------------------

@dataclass
class GridStats:
    """Pre-computed baselines built from a full year of data.

    Build once with GridStats.build(...); reuse for every explain_hour call.
    """
    # STL residuals for 5 system-level series, indexed by timestamp string
    residuals: pd.DataFrame          # cols: load, max_loading, solar, wind, slack
    residual_std: dict[str, float]   # std of each residual series

    # branch percentile table: MultiIndex (hour_of_day, is_workday) → branch loading pcts
    branch_pct90: pd.DataFrame       # shape (48 rows, n_branches cols)
    branch_pct95: pd.DataFrame
    branch_pct99: pd.DataFrame

    # forecast error baselines {metric: {mae, std}}
    forecast_error: dict[str, dict[str, float]]

    # raw metrics DataFrame (for find_interesting_days)
    metrics: pd.DataFrame

    # forecast + realtime aligned on datetime
    forecast: pd.DataFrame
    realtime: pd.DataFrame

    @classmethod
    def build(
        cls,
        ds: DataStore,
        fs: ForecastStore,
        rs: RealtimeStore,
        verbose: bool = True,
        workers: int = 1,
    ) -> "GridStats":
        if verbose:
            print("Building GridStats — single-pass scan of all snapshots…")

        # single pass: read each of the 8760 snapshots once for both system metrics
        # and per-branch loadings (avoids the 2× cost of calling them separately).
        # Resumable + tqdm progress bar when verbose; workers>1 parallelizes the scan.
        metrics, branch_df = ds.scan_all(progress=verbose, workers=workers)
        forecast = fs.system_forecast()
        realtime = rs.system_totals()

        if verbose:
            print("  Scan complete. Aligning forecast & realtime…")

        # --- align forecast & realtime on the snapshot index ---
        fc_aligned = forecast.reindex(metrics.index, method="nearest", tolerance="1h")
        rt_aligned = realtime.reindex(metrics.index, method="nearest", tolerance="1h")

        # --- build STL residuals for 5 series ---
        series_map = {
            "load":        metrics["total_load_mw"],
            "max_loading": metrics["max_line_loading_pct"],
            "solar":       rt_aligned["solar_mw"].fillna(0),
            "wind":        rt_aligned["wind_mw"].fillna(0),
            "slack":       metrics["slack_mw"],
        }

        residuals = {}
        series_iter = series_map.items()
        if verbose:
            from tqdm import tqdm
            series_iter = tqdm(list(series_map.items()), desc="STL decompose", unit="series")
        for name, s in series_iter:
            if verbose:
                series_iter.set_postfix_str(name)
            s_clean = s.interpolate().ffill().bfill()
            stl = STL(s_clean, period=24, robust=True)
            res = stl.fit()
            residuals[name] = res.resid

        resid_df = pd.DataFrame(residuals, index=metrics.index)
        resid_std = {col: float(resid_df[col].std()) for col in resid_df.columns}

        # --- branch percentile table from branch_df (no extra file reads) ---
        if verbose:
            print("  Building branch percentile table…")
        branch_pct90, branch_pct95, branch_pct99 = _build_branch_pcts_from_df(branch_df)

        # --- forecast error baselines ---
        # Error is defined as (actual − forecast) = the "surprise".  We store the
        # systematic bias (mean) AND std so callers can DE-BIAS: this dataset's DA
        # forecasts are scaled ~+23% (load) / +20% (solar) high every hour, so the
        # raw delta is mostly constant bias — the real signal is the de-biased
        # z-score  (surprise − bias) / std.
        if verbose:
            print("  Computing forecast error baselines…")
        fc_errors: dict[str, dict[str, float]] = {}
        for name, fc_col, rt_col in _SURPRISE_PAIRS:
            if fc_col not in fc_aligned.columns or rt_col not in rt_aligned.columns:
                continue
            err = (rt_aligned[rt_col] - fc_aligned[fc_col]).dropna()  # actual − forecast
            fc_errors[name] = {
                "bias": float(err.mean()),
                "std": float(err.std()) or 1.0,
                "mae": float(err.abs().mean()),
            }

        if verbose:
            print("  Done.")

        return cls(
            residuals=resid_df,
            residual_std=resid_std,
            branch_pct90=branch_pct90,
            branch_pct95=branch_pct95,
            branch_pct99=branch_pct99,
            forecast_error=fc_errors,
            metrics=metrics,
            forecast=fc_aligned,
            realtime=rt_aligned,
        )


def _build_branch_pcts_from_df(
    branch_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Compute branch loading percentiles stratified by (hour_of_day × is_workday).

    branch_df is the per-timestamp per-branch loading DataFrame from DataStore.scan_all().
    Returns three DataFrames (p90, p95, p99), each indexed by (hour, is_workday).
    """
    df = branch_df.copy()
    df["hour"] = df.index.hour
    df["is_workday"] = (df.index.dayofweek < 5).astype(int)
    df = df.set_index(["hour", "is_workday"], append=False)
    # drop the original datetime index level that's now gone
    branch_cols = [c for c in df.columns]
    p90 = df[branch_cols].groupby(level=["hour", "is_workday"]).quantile(0.90)
    p95 = df[branch_cols].groupby(level=["hour", "is_workday"]).quantile(0.95)
    p99 = df[branch_cols].groupby(level=["hour", "is_workday"]).quantile(0.99)
    return p90, p95, p99


def surprise_series(gs: GridStats) -> pd.DataFrame:
    """Hourly DE-BIASED forecast surprise z-score per metric (load/solar/wind).

    z = ((actual − forecast) − bias) / std, using the baselines in gs.forecast_error.
    Positive = more than the day-ahead plan (after removing the standing bias),
    so |z| is "how off-plan this hour really was".  Indexed like gs.metrics.
    """
    out: dict[str, pd.Series] = {}
    for name, fc_col, rt_col in _SURPRISE_PAIRS:
        base = gs.forecast_error.get(name)
        if base is None or fc_col not in gs.forecast.columns or rt_col not in gs.realtime.columns:
            continue
        err = gs.realtime[rt_col] - gs.forecast[fc_col]      # actual − forecast
        out[name] = (err - base["bias"]) / (base["std"] or 1.0)
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# explain_hour
# ---------------------------------------------------------------------------

def explain_hour(timestamp: str, gs: GridStats, ds: "DataStore | None" = None) -> dict:
    """Produce the LLM harness dict for a specific timestamp.

    Uses STL residuals (z-scores), forecast deltas, temporal momentum,
    and the branch percentile table to highlight what is unusual right now.

    Pass `ds` (a DataStore) to get per-branch loading details; otherwise
    only system-level max_loading is reported.
    """
    ts_dt = datetime.fromisoformat(timestamp)

    # --- system z-scores from STL residuals ---
    if timestamp in gs.residuals.index:
        row = gs.residuals.loc[timestamp]
    else:
        # nearest available
        idx = gs.residuals.index.get_indexer([pd.Timestamp(timestamp)], method="nearest")[0]
        row = gs.residuals.iloc[idx]

    z = {}
    for col in gs.residuals.columns:
        std = gs.residual_std.get(col, 1.0) or 1.0
        z[f"z_{col}"] = round(float(row[col]) / std, 2)

    # raw values
    m = gs.metrics.loc[timestamp] if timestamp in gs.metrics.index else gs.metrics.iloc[
        gs.metrics.index.get_indexer([pd.Timestamp(timestamp)], method="nearest")[0]
    ]

    system = {
        "total_load_mw":       round(float(m["total_load_mw"]), 1),
        "total_gen_mw":        round(float(m["total_gen_mw"]), 1),
        "max_line_loading_pct":round(float(m["max_line_loading_pct"]), 1),
        "slack_mw":            round(float(m["slack_mw"]), 1),
        **z,
    }

    # --- forecast deltas ---
    fc_deltas: dict = {}
    if timestamp in gs.forecast.index and timestamp in gs.realtime.index:
        fc = gs.forecast.loc[timestamp]
        rt = gs.realtime.loc[timestamp]
        for metric, fc_col, rt_col in [
            ("solar", "solar_mw",     "solar_mw"),
            ("wind",  "wind_mw",      "wind_mw"),
            ("load",  "load_total_mw","load_mw"),
        ]:
            if fc_col in fc.index and rt_col in rt.index:
                delta_mw = round(float(rt[rt_col]) - float(fc[fc_col]), 1)
                base = float(fc[fc_col]) or 1.0
                entry = {
                    "forecast_mw": round(float(fc[fc_col]), 1),
                    "actual_mw":   round(float(rt[rt_col]), 1),
                    "delta_mw":    delta_mw,
                    "delta_pct":   round(100 * delta_mw / abs(base), 1),
                }
                # de-biased surprise: how off-plan vs the operator's NORMAL error.
                # (raw delta is mostly the standing ~+20% forecast bias, not signal.)
                bl = gs.forecast_error.get(metric)
                if bl is not None:
                    entry["surprise_z"] = round((delta_mw - bl["bias"]) / (bl["std"] or 1.0), 2)
                fc_deltas[metric] = entry

    # --- temporal momentum ---
    momentum: dict = {}
    for lag_h, label in [(1, "1h"), (24, "24h")]:
        prev_ts = (ts_dt - timedelta(hours=lag_h)).isoformat()
        if prev_ts in gs.metrics.index:
            pm = gs.metrics.loc[prev_ts]
            momentum[f"load_delta_{label}_mw"] = round(
                float(m["total_load_mw"]) - float(pm["total_load_mw"]), 1
            )
            momentum[f"loading_delta_{label}_pct"] = round(
                float(m["max_line_loading_pct"]) - float(pm["max_line_loading_pct"]), 1
            )

    # --- stressed branches (above their 90th pct for this hour/workday) ---
    hour = ts_dt.hour
    is_workday = int(ts_dt.weekday() < 5)
    top_branches: list[dict] = []

    key = (hour, is_workday)
    if key in gs.branch_pct90.index:
        pct90_row = gs.branch_pct90.loc[key]
        pct95_row = gs.branch_pct95.loc[key]
        pct99_row = gs.branch_pct99.loc[key]

        if ds is not None:
            # read actual per-branch loadings from the snapshot
            net = ds.read_net(ds.nearest_timestamp(timestamp))
            actual_loadings: dict[str, float] = {}
            if getattr(net, "converged", False) and len(net.res_line):
                for idx, r in net.line.iterrows():
                    if idx in net.res_line.index:
                        val = net.res_line.at[idx, "loading_percent"]
                        if not math.isnan(val):
                            actual_loadings[str(r["name"])] = round(float(val), 1)

            for branch_name, actual in sorted(actual_loadings.items(), key=lambda x: -x[1]):
                if branch_name not in pct90_row.index:
                    continue
                thr90 = pct90_row[branch_name]
                if math.isnan(thr90) or actual < thr90:
                    continue
                thr99 = pct99_row[branch_name] if branch_name in pct99_row.index else float("nan")
                thr95 = pct95_row[branch_name] if branch_name in pct95_row.index else float("nan")
                pct_rank = 99 if (not math.isnan(thr99) and actual >= thr99) else (
                           95 if (not math.isnan(thr95) and actual >= thr95) else 90)
                top_branches.append({
                    "name": branch_name,
                    "loading_pct": actual,
                    "threshold_90th_pct": round(float(thr90), 1),
                    "pct_rank": pct_rank,
                })
                if len(top_branches) >= 10:
                    break

    # --- summary text for LLM context injection ---
    lines = [f"[{timestamp}]"]
    lines.append(
        f"Load {system['total_load_mw']} MW (z={z.get('z_load',0):+.1f}), "
        f"max line loading {system['max_line_loading_pct']}% (z={z.get('z_max_loading',0):+.1f}), "
        f"slack {system['slack_mw']:+.0f} MW (z={z.get('z_slack',0):+.1f})"
    )
    if fc_deltas:
        parts = []
        for metric, d in fc_deltas.items():
            sz = d.get("surprise_z")
            sz_txt = f", {sz:+.1f}σ" if sz is not None else ""
            parts.append(f"{metric} {d['delta_mw']:+.0f} MW ({d['delta_pct']:+.1f}%{sz_txt})")
        lines.append("Plan deviation (de-biased): " + ", ".join(parts))
    if momentum:
        m1h_load = momentum.get("load_delta_1h_mw")
        m1h_ldg = momentum.get("loading_delta_1h_pct")
        if m1h_load is not None:
            lines.append(
                f"Trend (1h): load {m1h_load:+.0f} MW, "
                f"max loading {m1h_ldg:+.1f}%"
            )
    if top_branches:
        names = ", ".join(b["name"] for b in top_branches[:3])
        lines.append(f"Stressed branches (≥90th pct): {names}")

    return {
        "timestamp": timestamp,
        "system": system,
        "forecast_deltas": fc_deltas,
        "momentum": momentum,
        "top_branches": top_branches,
        "summary_text": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# find_interesting_days
# ---------------------------------------------------------------------------

def find_interesting_days(gs: GridStats, n: int = 20) -> pd.DataFrame:
    """Rank all calendar days by their single biggest de-biased anomaly.

    "Max-of-surprises": each day's score is the largest of four daily |z| signals,
    so a flagged day always has one clear, narratable driver (the ``driver`` column):

      load_surprise_z   — de-biased day-ahead load plan deviation  ("on plan?")
      solar_surprise_z  — de-biased solar plan deviation
      wind_surprise_z   — de-biased wind plan deviation  (the noisiest series)
      loading_z         — max_line_loading anomaly vs its own seasonal pattern (STL)

    The slack series is intentionally dropped (22 MW noise floor → spurious z's).
    Raw, human-readable context columns (peak_loading_pct, peak_load_mw) are kept
    so the flag is explainable, not a black box.
    """
    by_date = lambda s: s.groupby(s.index.date)  # noqa: E731

    daily: dict[str, pd.Series] = {}

    # de-biased forecast surprise per metric → daily mean |z|
    surprise = surprise_series(gs)
    for metric in surprise.columns:
        daily[f"{metric}_surprise_z"] = by_date(surprise[metric].abs()).mean()

    # grid-stress anomaly: |STL residual| of max_line_loading, std-normalised
    if "max_loading" in gs.residuals.columns:
        std = gs.residual_std.get("max_loading", 1.0) or 1.0
        loading_z = (gs.residuals["max_loading"].abs() / std)
        daily["loading_z"] = by_date(loading_z).mean()

    df = pd.DataFrame(daily)

    # explainability context (raw units, not part of the score)
    df["peak_loading_pct"] = by_date(gs.metrics["max_line_loading_pct"]).max()
    df["peak_load_mw"] = by_date(gs.metrics["total_load_mw"]).max()

    # max-of-surprises score + which signal drove it
    z_cols = [c for c in df.columns if c.endswith("_z")]
    df["score"] = df[z_cols].max(axis=1)
    df["driver"] = (
        df[z_cols].idxmax(axis=1)
        .str.replace("_surprise_z", "", regex=False)
        .str.replace("_z", "", regex=False)
    )

    df.index = pd.to_datetime(df.index)
    ordered = ["score", "driver"] + z_cols + ["peak_loading_pct", "peak_load_mw"]
    return df[ordered].sort_values("score", ascending=False).head(n)


# ---------------------------------------------------------------------------
# artifact persistence
# ---------------------------------------------------------------------------

def _peak_hour_ts(gs: GridStats, day) -> str:
    """ISO timestamp of the peak max-line-loading hour on a given calendar day."""
    day_mask = gs.metrics.index.date == pd.Timestamp(day).date()
    return gs.metrics.loc[day_mask]["max_line_loading_pct"].idxmax().isoformat()


def save_artifacts(
    gs: GridStats,
    ds: DataStore,
    out_dir: "Path | None" = None,
    n_days: int = 30,
    verbose: bool = True,
) -> Path:
    """Persist the build outputs so the pitch day can be picked without rescanning.

    Writes to ``out_dir`` (default config.OUTPUT_DIR):
      metrics.parquet, residuals.parquet, branch_loadings.parquet,
      interesting_days.csv, top_day_explain.json
    """
    out = Path(out_dir) if out_dir else config.OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    gs.metrics.to_parquet(out / "metrics.parquet")
    gs.residuals.to_parquet(out / "residuals.parquet")

    _, branch = ds.scan_all()  # cached from build() — free
    branch.to_parquet(out / "branch_loadings.parquet")

    days = find_interesting_days(gs, n=n_days)
    days.to_csv(out / "interesting_days.csv")

    if len(days):
        top_ts = _peak_hour_ts(gs, days.index[0])
        explain = explain_hour(top_ts, gs, ds=ds)
        (out / "top_day_explain.json").write_text(
            json.dumps(explain, indent=2, default=str), encoding="utf-8"
        )

    if verbose:
        print(f"\nArtifacts written to: {out}")
    return out


# ---------------------------------------------------------------------------
# full build entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    import sys

    from .loader import DataStore, ForecastStore, RealtimeStore

    # workers: CLI arg overrides; else default to (cores-1) capped at 8.
    # 1 = serial. Parallel path needs this __main__ guard (Windows spawn).
    default_workers = max(1, min(8, (os.cpu_count() or 2) - 1))
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else default_workers
    print(f"Scanning with {workers} worker process(es) "
          f"(override: python -m case_study.analysis <N>)")

    ds = DataStore()
    fs = ForecastStore()
    rs = RealtimeStore()

    gs = GridStats.build(ds, fs, rs, verbose=True, workers=workers)
    out = save_artifacts(gs, ds, n_days=30)

    print("\nTop 5 interesting days:")
    top = find_interesting_days(gs, n=5)
    print(top.to_string())

    print("\nSample explain_hour for the top day:")
    top_ts = _peak_hour_ts(gs, top.index[0])
    result = explain_hour(top_ts, gs, ds=ds)
    print(result["summary_text"])
