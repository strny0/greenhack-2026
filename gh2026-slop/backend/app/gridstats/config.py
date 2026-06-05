"""gridstats configuration — standalone, env-overridable, no app.* imports."""
from __future__ import annotations

import os
from pathlib import Path

_HERE = Path(__file__).resolve()

# repo dataset lives at <repo>/dataset/data; gridstats is
# .../gh2026-slop/backend/app/gridstats, so parents[4] == <repo>.
DATA_DIR = Path(
    os.environ.get("GRIDSTATS_DATA_DIR", _HERE.parents[4] / "dataset" / "data")
)
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
STATIC_DIR    = DATA_DIR / "static"
FORECASTS_DIR = DATA_DIR / "forecasts"
REALTIME_DIR  = DATA_DIR / "realtime"

# Precomputed bundle + resumable scan checkpoints (default: package's own target/).
TARGET_DIR = Path(
    os.environ.get("GRIDSTATS_TARGET_DIR", _HERE.parent / "target")
)
CACHE_DIR = TARGET_DIR / "cache"  # resumable scan checkpoints

# Back-compat aliases used by the loader's offline scan paths.
OUTPUT_DIR = TARGET_DIR

# California bounding box (NREL-118 regions: r1=Bay Area, r2=Sacramento, r3=San Diego)
LON_MIN, LON_MAX = -124.5, -114.5
LAT_MIN, LAT_MAX =   32.5,   42.0

# Alert thresholds (kept in sync with backend)
LINE_LOADING_WARN  = 75.0
LINE_LOADING_ALERT = 90.0
VOLTAGE_WARN_MARGIN = 0.01
