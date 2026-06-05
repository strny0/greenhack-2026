"""Statistical harness for grid case-study analysis.

GridStats   — pre-computed STL decomposition + branch percentile table
explain_hour — produces the LLM context dict for a specific timestamp
find_interesting_days — ranks all 365 calendar days by anomaly composite score
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL

from .loader import DataStore, ForecastStore, RealtimeStore


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
    ) -> "GridStats":
        if verbose:
            print("Building GridStats — single-pass scan of all snapshots…")

        # single pass: read each of the 8760 snapshots once for both system metrics
        # and per-branch loadings (avoids the 2× cost of calling them separately)
        metrics, branch_df = ds.scan_all()
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
        for name, s in series_map.items():
            if verbose:
                print(f"  STL decomposing {name}…")
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
        if verbose:
            print("  Computing forecast error baselines…")
        fc_errors: dict[str, dict[str, float]] = {}
        pairs = [
            ("solar",  "solar_mw",       rt_aligned.get("solar_mw")),
            ("wind",   "wind_mw",         rt_aligned.get("wind_mw")),
            ("load",   "load_total_mw",   rt_aligned.get("load_mw")),
        ]
        for name, fc_col, rt_series in pairs:
            if fc_col not in fc_aligned.columns or rt_series is None:
                continue
            err = (fc_aligned[fc_col] - rt_series).dropna()
            fc_errors[name] = {"mae": float(err.abs().mean()), "std": float(err.std())}

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
                fc_deltas[metric] = {
                    "forecast_mw": round(float(fc[fc_col]), 1),
                    "actual_mw":   round(float(rt[rt_col]), 1),
                    "delta_mw":    delta_mw,
                    "delta_pct":   round(100 * delta_mw / abs(base), 1),
                }

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
            parts.append(f"{metric} {d['delta_mw']:+.0f} MW ({d['delta_pct']:+.1f}% vs forecast)")
        lines.append("Forecast error: " + ", ".join(parts))
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
    """Rank all calendar days by anomaly composite score.

    Scores each day by:
      composite_z        — mean |z-score| across 5 system metrics
      max_branch_stress  — peak max_line_loading_pct for the day
      forecast_error_mw  — mean abs forecast error (solar+wind+load) that day
      n_alert_hours      — hours with max_line_loading >= LINE_LOADING_ALERT
    """
    from . import config

    df = gs.residuals.copy()
    df["date"] = df.index.date

    # composite_z: mean of absolute z-scores across all metrics
    for col in gs.residuals.columns:
        std = gs.residual_std.get(col, 1.0) or 1.0
        df[f"abs_z_{col}"] = df[col].abs() / std

    z_cols = [c for c in df.columns if c.startswith("abs_z_")]
    daily_z = df.groupby("date")[z_cols].mean().mean(axis=1).rename("composite_z")

    # max branch stress
    daily_max_loading = (
        gs.metrics["max_line_loading_pct"]
        .groupby(gs.metrics.index.date)
        .max()
        .rename("max_branch_stress_pct")
    )

    # n_alert_hours
    n_alerts = (
        (gs.metrics["max_line_loading_pct"] >= config.LINE_LOADING_ALERT)
        .groupby(gs.metrics.index.date)
        .sum()
        .rename("n_alert_hours")
    )

    # forecast error (if available)
    fc_err_parts = []
    if not gs.forecast.empty and not gs.realtime.empty:
        for fc_col, rt_col in [("solar_mw", "solar_mw"), ("wind_mw", "wind_mw"), ("load_total_mw", "load_mw")]:
            if fc_col in gs.forecast.columns and rt_col in gs.realtime.columns:
                err = (gs.forecast[fc_col] - gs.realtime[rt_col]).abs()
                fc_err_parts.append(err)
    if fc_err_parts:
        total_err = sum(fc_err_parts)
        daily_fc_err = total_err.groupby(total_err.index.date).mean().rename("forecast_error_mw")
    else:
        daily_fc_err = pd.Series(dtype=float, name="forecast_error_mw")

    result = pd.concat([daily_z, daily_max_loading, n_alerts, daily_fc_err], axis=1)
    result.index = pd.to_datetime(result.index)
    result = result.sort_values("composite_z", ascending=False)
    return result.head(n)


# ---------------------------------------------------------------------------
# smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from .loader import DataStore, ForecastStore, RealtimeStore

    ds = DataStore()
    fs = ForecastStore()
    rs = RealtimeStore()

    gs = GridStats.build(ds, fs, rs)

    print("\nTop 5 interesting days:")
    top = find_interesting_days(gs, n=5)
    print(top.to_string())

    print("\nSample explain_hour for the top day:")
    top_ts = gs.metrics.loc[
        gs.metrics.index.date == top.index[0].date()
    ]["max_line_loading_pct"].idxmax().isoformat()

    result = explain_hour(top_ts, gs, ds=ds)
    print(result["summary_text"])
