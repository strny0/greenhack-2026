"""One-time offline build CLI for the gridstats bundle.

Run from the backend dir so ``app.gridstats`` is importable:

    python -m app.gridstats.build [WORKERS]

Scans all 8760 hourly snapshots (resumable) and writes the complete ``target/``
bundle. Runs ONCE; subsequent app runs read the bundle via GridStats.load().
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import config
from .artifacts import save_bundle
from .insights import interesting_days
from .loader import DataStore, ForecastStore, RealtimeStore
from .stats import GridStatsBundle

_BANNER_WIDTH = 64


def _available_cpus() -> int:
    """CPUs actually usable here — honouring container limits, not just the host.

    ``os.cpu_count()`` reports the host's cores and ignores a Docker ``--cpus``
    quota or a cpuset, so it over-subscribes in CI / constrained containers. We
    check the cgroup v2 CPU quota and the scheduler affinity first.
    """
    try:  # cgroup v2 quota (Docker --cpus): "<quota> <period>" or "max <period>"
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()[:2]
        if quota != "max":
            n = int(int(quota) // int(period))
            if n >= 1:
                return n
    except (OSError, ValueError):
        pass
    try:  # honours --cpuset-cpus / taskset
        return len(os.sched_getaffinity(0))
    except AttributeError:  # macOS / Windows
        return os.cpu_count() or 2


def _default_workers() -> int:
    """Worker process count: ``GRIDSTATS_BUILD_WORKERS`` if set, else one fewer
    than the available CPUs, capped at 8 (1 = serial)."""
    override = os.environ.get("GRIDSTATS_BUILD_WORKERS")
    if override:
        return max(1, int(override))
    return max(1, min(8, _available_cpus() - 1))


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

    # workers precedence: CLI arg > GRIDSTATS_BUILD_WORKERS env > auto (CPUs-1,
    # capped at 8, container-aware). 1 = serial. The parallel path needs this
    # __main__ guard (Windows spawn).
    workers = int(argv[0]) if argv else _default_workers()

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
