"""Bundle persistence: save_bundle (offline) / load_bundle (runtime).

The bundle is the complete precomputed state so runtime never rescans snapshots
or touches pandapower. Layout under ``dir`` (default config.TARGET_DIR):

    metrics.parquet          per-hour system metrics
    branch_loadings.parquet  per-hour per-branch loading_percent
    residuals.parquet        STL residuals (5 series)
    forecast.parquet         DA forecast, aligned to metrics index
    realtime.parquet         actuals, aligned to metrics index
    branch_pct90/95/99.parquet  stratified (hour×workday) normal bands
    baselines.json           forecast_error, residual_std, dataset bounds,
                             build timestamp, schema version
    interesting_days.csv     precomputed ranking
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import config
from .stats import GridStatsBundle

SCHEMA_VERSION = 2


def save_bundle(
    gs: GridStatsBundle,
    out_dir: "Path | None" = None,
    n_days: int = 30,
    verbose: bool = True,
) -> Path:
    """Write a complete bundle so runtime can serve without rescanning.

    ``n_days`` is the size of the precomputed interesting_days ranking written to
    interesting_days.csv (insights.interesting_days filters/re-ranks at query time,
    but a generous precomputed table keeps the bundle self-describing).
    """
    out = Path(out_dir) if out_dir else config.TARGET_DIR
    out.mkdir(parents=True, exist_ok=True)

    gs.metrics.to_parquet(out / "metrics.parquet")
    gs.branch_loadings.to_parquet(out / "branch_loadings.parquet")
    gs.residuals.to_parquet(out / "residuals.parquet")
    gs.forecast.to_parquet(out / "forecast.parquet")
    gs.realtime.to_parquet(out / "realtime.parquet")
    gs.branch_pct90.to_parquet(out / "branch_pct90.parquet")
    gs.branch_pct95.to_parquet(out / "branch_pct95.parquet")
    gs.branch_pct99.to_parquet(out / "branch_pct99.parquet")

    # deterministic deviation-risk timeline (one row per hour) — computed here from
    # the already-built bundle so the runtime endpoint serves it without recomputing.
    from .deviation import deviation_timeline

    deviation_timeline(gs).to_parquet(out / "deviation_timeline.parquet")

    baselines = {
        "forecast_error": gs.forecast_error,
        "residual_std": gs.residual_std,
        "first_ts": gs.first_ts or gs.metrics.index[0].isoformat(),
        "last_ts": gs.last_ts or gs.metrics.index[-1].isoformat(),
        "built_at": gs.built_at or pd.Timestamp.utcnow().isoformat(),
        "schema_version": gs.schema_version or SCHEMA_VERSION,
    }
    (out / "baselines.json").write_text(
        json.dumps(baselines, indent=2), encoding="utf-8"
    )

    # precomputed ranking (lazy import to avoid a stats↔insights cycle at import time)
    from .insights import interesting_days as _interesting_days

    days = _interesting_days(gs, gs.first_ts, gs.last_ts, n=n_days)
    days.to_csv(out / "interesting_days.csv")

    if verbose:
        print(f"\nBundle written to: {out}")
    return out


def _restratify(df: pd.DataFrame) -> pd.DataFrame:
    """Rebuild the (hour, is_workday) MultiIndex from a round-tripped parquet."""
    if {"hour", "is_workday"}.issubset(df.columns):
        return df.set_index(["hour", "is_workday"]).sort_index()
    return df


def load_bundle(dir: "Path | None" = None) -> GridStatsBundle:
    """Reconstruct a GridStatsBundle purely from the saved files.

    No DataStore, no pandapower. Raises a clear error if the bundle is missing,
    instructing the user to run the one-time build.
    """
    d = Path(dir) if dir else config.TARGET_DIR
    metrics_path = d / "metrics.parquet"
    if not metrics_path.exists():
        raise FileNotFoundError(
            f"gridstats bundle not found at {d}. Run the one-time build first:\n"
            f"    python -m app.gridstats.build\n"
            f"(missing {metrics_path.name})"
        )

    metrics = pd.read_parquet(metrics_path)
    branch_loadings = pd.read_parquet(d / "branch_loadings.parquet")
    residuals = pd.read_parquet(d / "residuals.parquet")
    forecast = pd.read_parquet(d / "forecast.parquet")
    realtime = pd.read_parquet(d / "realtime.parquet")
    branch_pct90 = _restratify(pd.read_parquet(d / "branch_pct90.parquet"))
    branch_pct95 = _restratify(pd.read_parquet(d / "branch_pct95.parquet"))
    branch_pct99 = _restratify(pd.read_parquet(d / "branch_pct99.parquet"))

    baselines = json.loads((d / "baselines.json").read_text(encoding="utf-8"))

    # deviation timeline is optional: a v1 bundle predates it, in which case it is
    # left as None and recomputed on first access from the loaded bundle.
    deviation_path = d / "deviation_timeline.parquet"
    deviation = pd.read_parquet(deviation_path) if deviation_path.exists() else None

    return GridStatsBundle(
        residuals=residuals,
        residual_std=baselines.get("residual_std", {}),
        branch_pct90=branch_pct90,
        branch_pct95=branch_pct95,
        branch_pct99=branch_pct99,
        forecast_error=baselines.get("forecast_error", {}),
        metrics=metrics,
        forecast=forecast,
        realtime=realtime,
        branch_loadings=branch_loadings,
        deviation=deviation,
        first_ts=baselines.get("first_ts", metrics.index[0].isoformat()),
        last_ts=baselines.get("last_ts", metrics.index[-1].isoformat()),
        built_at=baselines.get("built_at", ""),
        schema_version=int(baselines.get("schema_version", SCHEMA_VERSION)),
    )
