"""Case-study configuration — standalone, no dotenv, no FastAPI."""
from __future__ import annotations

from pathlib import Path

# dataset/data/ relative to workspace root
DATA_DIR = Path(__file__).resolve().parents[2] / "dataset" / "data"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
STATIC_DIR    = DATA_DIR / "static"
FORECASTS_DIR = DATA_DIR / "forecasts"
REALTIME_DIR  = DATA_DIR / "realtime"

# California bounding box (NREL-118 regions: r1=Bay Area, r2=Sacramento, r3=San Diego)
LON_MIN, LON_MAX = -124.5, -114.5
LAT_MIN, LAT_MAX =   32.5,   42.0

# Alert thresholds (kept in sync with backend)
LINE_LOADING_WARN  = 75.0
LINE_LOADING_ALERT = 90.0
VOLTAGE_WARN_MARGIN = 0.01
