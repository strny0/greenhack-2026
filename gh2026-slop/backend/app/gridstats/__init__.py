"""gridstats — historical/statistical grid-analysis library.

Public entry point: the ``GridStats`` facade. It holds a precomputed
``GridStatsBundle`` (loaded from a ``target/`` bundle) and binds the insight
functions to it. Runtime serving uses ``GridStats.load()`` and never touches
pandapower or the raw snapshots; the offline ``GridStats.build()`` produces the
bundle.

Separability: nothing here imports from ``app.*`` — only this package plus
pandas/numpy/statsmodels/pyarrow/tqdm/pandapower.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import config, insights
from .artifacts import load_bundle, save_bundle
from .stats import GridStatsBundle

__all__ = ["GridStats", "GridStatsBundle"]


class GridStats:
    """Facade over a precomputed GridStatsBundle.

    Load a bundle once and call the insight methods; they serve entirely from
    the bundle (no snapshots, no pandapower).
    """

    def __init__(self, bundle: GridStatsBundle) -> None:
        self.bundle = bundle

    # --- construction --------------------------------------------------------

    @classmethod
    def load(cls, bundle_dir: "str | Path | None" = None) -> "GridStats":
        """Load a precomputed bundle from ``bundle_dir`` (default config.TARGET_DIR)."""
        d = Path(bundle_dir) if bundle_dir else config.TARGET_DIR
        return cls(load_bundle(d))

    @classmethod
    def build(
        cls,
        verbose: bool = True,
        workers: int = 1,
        bundle_dir: "str | Path | None" = None,
        save: bool = True,
    ) -> "GridStats":
        """Offline build: scan snapshots → bundle, optionally save it, return facade.

        Requires the dataset + pandapower (offline only). Delegates to
        stats.GridStatsBundle.build and artifacts.save_bundle.
        """
        # local import keeps the loader (pandapower) out of the runtime path
        from .loader import DataStore, ForecastStore, RealtimeStore

        ds = DataStore()
        fs = ForecastStore()
        rs = RealtimeStore()
        bundle = GridStatsBundle.build(ds, fs, rs, verbose=verbose, workers=workers)
        if save:
            d = Path(bundle_dir) if bundle_dir else config.TARGET_DIR
            save_bundle(bundle, d, verbose=verbose)
        return cls(bundle)

    # --- insight methods (bind the held bundle) ------------------------------

    def interesting_days(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        n: int = 10,
    ) -> pd.DataFrame:
        """Rank calendar days in [start_date, end_date] by their biggest de-biased anomaly.

        "Score" is the largest of four daily mean |z| signals
        (load_surprise_z, solar_surprise_z, wind_surprise_z, loading_z).
        Each flagged day has one clear ``driver`` — the dominant anomalous series —
        making the result directly narratable.

        Example:
            gs.interesting_days("2024-09-01", "2024-09-30", 5)
            # Returns DataFrame (index=date, sorted by score desc):
            #
            #              score  driver  load_z  solar_z  wind_z  loading_z  peak_loading_pct  peak_load_mw
            # 2024-09-13   2.38   wind    1.02    1.29     2.38    0.87       53.35             12432.45
            # 2024-09-04   2.12   load    2.12    0.82     1.10    0.42       42.26             10462.17
            #
            # 2024-09-13: wind generation underdelivered by ~2.4σ all day, dragging
            # the grid onto imports (high surprise_z on load too, but wind dominated).

        Agent use: only range tool — "which days in Q3 were most unusual / worth reviewing".
        For a single hour use explain_hour or deep_dive instead.
        """
        return insights.interesting_days(self.bundle, start_date, end_date, n)

    def explain_hour(self, timestamp: str) -> dict:
        """Compact anomaly snapshot for a single hour (lightweight).

        Returns system metrics with STL z-scores, de-biased plan deviation per metric
        (load/solar/wind), top-3 stressed branches vs their p90–p99 normal band,
        1-hour momentum, and a ready-to-inject ``summary_text``.

        Example:
            gs.explain_hour("2024-09-13T18:00:00")
            # {
            #   "timestamp": "2024-09-13T18:00:00",
            #   "system": {
            #     "total_load_mw": 11938.3, "total_gen_mw": 12125.1,
            #     "max_line_loading_pct": 51.2, "slack_mw": 115.2,
            #     "z_load": 0.3, "z_max_loading": 0.2, "z_wind": -0.12
            #   },
            #   "forecast_deltas": {
            #     "wind":  {"forecast_mw": 464.6, "actual_mw": 274.2,
            #               "delta_mw": -190.4, "delta_pct": -41.0, "surprise_z": -1.84},
            #     "load":  {"delta_mw": -455.8, "surprise_z": 2.31},
            #     "solar": {"delta_mw": -50.0,  "surprise_z": 0.33}
            #   },
            #   "momentum": {"load_delta_1h_mw": 635.6, "loading_delta_1h_pct": -0.5},
            #   "top_branches": [
            #     {"name": "branch_017_113_1", "loading_pct": 48.5,
            #      "threshold_90th_pct": 47.4, "pct_rank": 90}
            #   ],
            #   "summary_text": "[2024-09-13T18:00:00]\\n
            #     Load 11938.3 MW (z=+0.3), max line loading 51.2% (z=+0.2) ...\\n
            #     Plan deviation (de-biased): wind -190 MW (-41.0%, -1.8σ) ..."
            # }
            #
            # Reading: wind underdelivered by 190 MW at 18:00 (−1.8σ de-biased),
            # load was -456 MW vs forecast (+2.3σ de-biased surprise because the
            # bias-corrected model predicted more). Load jumped +636 MW in the last hour.

        Agent use: default tool for "what happened at <time>" / "was this hour anomalous".
        """
        return insights.explain_hour(self.bundle, timestamp)

    def plan_adherence(self, day: str) -> dict:
        """Per-metric de-biased plan adherence over a full calendar day (lightweight).

        For each metric (load/solar/wind): mean |σ| over the day, the worst hour and
        its signed σ. Verdict: "on plan" if all metrics stay within ±2σ de-biased,
        otherwise "off plan: <metric> hit <σ>σ".

        Example:
            gs.plan_adherence("2024-09-13")
            # {
            #   "day": "2024-09-13",
            #   "off_plan": True,
            #   "verdict": "off plan: wind hit -3.2σ (de-biased) on 2024-09-13",
            #   "metrics": {
            #     "wind":  {"mean_abs_sigma": 2.38, "worst_hour": "2024-09-13T15:00:00",
            #               "worst_sigma": -3.2},
            #     "solar": {"mean_abs_sigma": 1.29, "worst_sigma": -3.17},
            #     "load":  {"mean_abs_sigma": 1.02, "worst_sigma":  2.81}
            #   },
            #   "worst_metric": "wind", "worst_sigma": -3.2
            # }
            #
            # Reading: wind was off plan all day (mean 2.38σ deviation); worst at 15:00
            # where it underdelivered by 3.2 de-biased standard deviations.
            # Solar also missed significantly (−3.2σ at 13:00).

        Agent use: "did this day go to plan / how off-plan was the forecast".
        """
        return insights.plan_adherence(self.bundle, day)

    def loading_context(self, timestamp: str, top: int = 5) -> dict:
        """Top-N branches by loading at one hour vs their statistical normal band.

        For each branch: actual loading_pct and the p90/p95/p99 band for this
        hour-of-day × workday stratum. ``pct_rank`` = 0 means below p90 (normal),
        90/95/99 means at or above that percentile.

        Example:
            gs.loading_context("2024-09-13T18:00:00", top=5)
            # {
            #   "timestamp": "2024-09-13T18:00:00",
            #   "branches": [
            #     {"name": "branch_011_012_1", "loading_pct": 51.2,
            #      "p90": 53.4, "p95": 55.8, "p99": 57.3, "pct_rank": 0},   ← below p90 = normal
            #     {"name": "branch_017_113_1", "loading_pct": 48.5,
            #      "p90": 47.4, "p95": 48.5, "p99": 51.4, "pct_rank": 90},  ← at/above p90
            #     {"name": "branch_094_100_1", "loading_pct": 37.9,
            #      "p90": 38.1, "p95": 38.9, "p99": 42.7, "pct_rank": 0},
            #     ...
            #   ],
            #   "summary_text": "[2024-09-13T18:00:00] top 5 branch loadings vs normal band\\n
            #     branch_011_012_1: 51.2% (p90/95/99=53.4/55.8/57.3, ~0th)\\n
            #     branch_017_113_1: 48.5% (p90/95/99=47.4/48.5/51.4, ~90th) ..."
            # }
            #
            # Reading: branch_011_012_1 is the most loaded line by raw % but still
            # below its normal p90 for a Friday evening — not anomalous.
            # branch_017_113_1 is above its p90 threshold for this hour/day type.

        Agent use: "is this line unusually loaded" / "which lines are above their typical range".
        Complements most_loaded_lines (live ranking) with the historical norm context.
        """
        return insights.loading_context(self.bundle, timestamp, top)

    def deep_dive(self, timestamp: str) -> dict:
        """Exhaustive single-hour breakdown — VERBOSE & EXPENSIVE context.

        Returns all system metrics raw + z, full per-metric plan deviation
        (forecast/actual/delta/σ), ALL stressed branches (≥p90 for hour×workday),
        momentum at 1h and 24h, and the full day plan-adherence context.

        Example (condensed):
            gs.deep_dive("2024-09-13T18:00:00")
            # {
            #   "timestamp": "2024-09-13T18:00:00",
            #   "system": {
            #     "total_load_mw": 11938.3, "max_line_loading_pct": 51.2,
            #     "n_overloaded_lines": 0, "converged": True,
            #     "z": {
            #       "load":        {"residual": 134.4, "z": 0.3},
            #       "max_loading": {"residual": 0.6,   "z": 0.2},
            #       "wind":        {"residual": -13.6,  "z": -0.12}
            #     }
            #   },
            #   "momentum": {
            #     "load_delta_1h_mw":       635.6,  "loading_delta_1h_pct":  -0.5,
            #     "load_delta_24h_mw":     -352.4,  "loading_delta_24h_pct":  0.3
            #   },
            #   "stressed_branches": [  # 71 branches ≥ p90 at this hour
            #     {"name": "branch_017_113_1", "loading_pct": 48.5,
            #      "threshold_90th_pct": 47.4, "pct_rank": 90}, ...
            #   ],
            #   "day_context": { "off_plan": True,
            #     "verdict": "off plan: wind hit -3.2σ (de-biased) on 2024-09-13" },
            #   "summary_text": "[2024-09-13T18:00:00] DEEP DIVE\\n..."
            # }

        Agent use: only when the operator explicitly requests a full / in-depth breakdown.
        explain_hour and loading_context answer most questions more cheaply.
        """
        return insights.deep_dive(self.bundle, timestamp)
