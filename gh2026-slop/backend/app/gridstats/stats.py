"""Statistical core: the precomputed GridStatsBundle dataclass + offline build().

GridStatsBundle  — pre-computed STL decomposition + branch percentile table +
                   de-biased forecast-error baselines, built once from a full year.
surprise_series  — hourly de-biased forecast surprise z per metric (load/solar/wind).

This module is OFFLINE: build() scans snapshots via the loader. Runtime serving
reconstructs a GridStatsBundle from the saved bundle (see artifacts.load_bundle),
which never touches pandapower or the snapshots.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from statsmodels.tsa.seasonal import STL

from .loader import DataStore, ForecastStore, RealtimeStore

# (metric, forecast column, realtime column) — the three day-ahead vs actual pairs
_SURPRISE_PAIRS = [
    ("load",  "load_total_mw", "load_mw"),
    ("solar", "solar_mw",      "solar_mw"),
    ("wind",  "wind_mw",       "wind_mw"),
]


# ---------------------------------------------------------------------------
# GridStatsBundle
# ---------------------------------------------------------------------------

@dataclass
class GridStatsBundle:
    """Pre-computed baselines built from a full year of data.

    Build once with GridStatsBundle.build(...) (offline) or reconstruct from a
    saved bundle with artifacts.load_bundle(...) (runtime); reuse for every query.
    """
    # STL residuals for 5 system-level series, indexed by timestamp
    residuals: pd.DataFrame          # cols: load, max_loading, solar, wind, slack
    residual_std: dict[str, float]   # std of each residual series

    # branch percentile table: MultiIndex (hour_of_day, is_workday) → branch loading pcts
    branch_pct90: pd.DataFrame       # shape (48 rows, n_branches cols)
    branch_pct95: pd.DataFrame
    branch_pct99: pd.DataFrame

    # forecast error baselines {metric: {bias, std, mae}} (error = actual − forecast)
    forecast_error: dict[str, dict[str, float]]

    # raw per-hour system metrics
    metrics: pd.DataFrame

    # forecast + realtime aligned on the metrics index
    forecast: pd.DataFrame
    realtime: pd.DataFrame

    # per-hour per-branch loading_percent (cols = branch names), shared metrics index
    branch_loadings: pd.DataFrame

    # per-hour deterministic deviation-risk timeline (see deviation.py). Populated
    # lazily: None on a freshly-built or v1 bundle, computed on first access and
    # cached here by the GridStats facade. Persisted as deviation_timeline.parquet.
    deviation: "pd.DataFrame | None" = None

    # dataset window + provenance (populated by build/load)
    first_ts: str = ""
    last_ts: str = ""
    built_at: str = ""
    schema_version: int = 1

    @classmethod
    def build(
        cls,
        ds: DataStore,
        fs: ForecastStore,
        rs: RealtimeStore,
        verbose: bool = True,
        workers: int = 1,
    ) -> "GridStatsBundle":
        if verbose:
            print("Building GridStatsBundle — single-pass scan of all snapshots…")

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

        first_ts = metrics.index[0].isoformat()
        last_ts = metrics.index[-1].isoformat()
        built_at = pd.Timestamp.utcnow().isoformat()

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
            branch_loadings=branch_df,
            first_ts=first_ts,
            last_ts=last_ts,
            built_at=built_at,
            schema_version=2,
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
    branch_cols = [c for c in df.columns]
    p90 = df[branch_cols].groupby(level=["hour", "is_workday"]).quantile(0.90)
    p95 = df[branch_cols].groupby(level=["hour", "is_workday"]).quantile(0.95)
    p99 = df[branch_cols].groupby(level=["hour", "is_workday"]).quantile(0.99)
    return p90, p95, p99


def surprise_series(gs: GridStatsBundle) -> pd.DataFrame:
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
