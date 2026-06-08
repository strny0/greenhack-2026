"""One-time offline build CLI for the gridstats bundle.

Run from the backend dir so ``app.gridstats`` is importable:

    python -m app.gridstats.build [WORKERS]

Scans all 8760 hourly snapshots (resumable) and writes the complete ``target/``
bundle. Runs ONCE; subsequent app runs read the bundle via GridStats.load().
"""
from __future__ import annotations

import os
import sys

from . import config
from .artifacts import save_bundle
from .insights import interesting_days
from .loader import DataStore, ForecastStore, RealtimeStore
from .stats import GridStatsBundle

_BANNER_WIDTH = 64


def _banner(workers: int) -> str:
    bar = "═" * _BANNER_WIDTH
    return "\n".join([
        bar,
        "  gridstats: ONE-TIME PRECOMPUTE",
        "  Scanning 8760 hourly snapshots → target/ bundle.",
        "  This runs ONCE (resumable). Subsequent app runs read the bundle.",
        f"  Using {workers} worker process(es).",
        bar,
    ])


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    # workers: CLI arg overrides; else default to (cores-1) capped at 8.
    # 1 = serial. The parallel path needs this __main__ guard (Windows spawn).
    default_workers = max(1, min(8, (os.cpu_count() or 2) - 1))
    workers = int(argv[0]) if argv else default_workers

    print(_banner(workers))

    ds = DataStore()
    fs = ForecastStore()
    rs = RealtimeStore()

    gs = GridStatsBundle.build(ds, fs, rs, verbose=True, workers=workers)
    out = save_bundle(gs, config.TARGET_DIR, verbose=True)

    print("\nTop 5 interesting days:")
    top = interesting_days(gs, gs.first_ts, gs.last_ts, n=5)
    print(top.to_string())

    print(f"\nBundle ready at: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
