"""gridstats configuration — standalone, env-overridable, no app.* imports."""
from __future__ import annotations

import os
from pathlib import Path

_HERE = Path(__file__).resolve()
# gridstats is .../gh2026-slop/backend/app/gridstats, so:
#   parents[3] == gh2026-slop   parents[4] == <repo>
_APP_ROOT = _HERE.parents[3]
_REPO_ROOT = _HERE.parents[4]


def _resolve_data_dir() -> Path:
    """Locate the extracted ČEPS dataset's inner ``data/`` dir.

    Precedence (first match wins) — explicit env vars are honoured
    unconditionally; the historical ``<repo>/dataset/data`` default is kept as
    the final fallback so existing setups keep working. In between we now also
    discover the path the main app (app/config.py) defaults to, so a plain
    ``python -m app.gridstats.build`` works without any env var.
    """
    # 1. explicit override for gridstats; 2. shared with the main app.
    for var in ("GRIDSTATS_DATA_DIR", "GRID_DATA_DIR"):
        if os.environ.get(var):
            return Path(os.environ[var])
    # 3. main app's default location (see app/config.py); 4. legacy default.
    app_default = _APP_ROOT / "data" / "greenhack-2026-ČEPS-dataset" / "data"
    legacy_default = _REPO_ROOT / "dataset" / "data"
    if app_default.exists():
        return app_default
    return legacy_default


DATA_DIR = _resolve_data_dir()
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
