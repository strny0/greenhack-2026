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
        return insights.interesting_days(self.bundle, start_date, end_date, n)

    def explain_hour(self, timestamp: str) -> dict:
        return insights.explain_hour(self.bundle, timestamp)

    def plan_adherence(self, day: str) -> dict:
        return insights.plan_adherence(self.bundle, day)

    def loading_context(self, timestamp: str, top: int = 5) -> dict:
        return insights.loading_context(self.bundle, timestamp, top)

    def deep_dive(self, timestamp: str) -> dict:
        return insights.deep_dive(self.bundle, timestamp)
