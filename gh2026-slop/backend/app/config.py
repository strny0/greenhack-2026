"""Central configuration: data paths, alert thresholds, AI provider settings.

All operator-tunable knobs live here so they can be changed in one place.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Data location -----------------------------------------------------------
# Points at the extracted ČEPS dataset's inner `data/` directory.
_DEFAULT_DATA = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "greenhack-2026-ČEPS-dataset"
    / "data"
)
DATA_DIR = Path(os.getenv("GRID_DATA_DIR", str(_DEFAULT_DATA)))
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
STATIC_DIR = DATA_DIR / "static"
FORECASTS_DIR = DATA_DIR / "forecasts"
REALTIME_DIR = DATA_DIR / "realtime"

# --- Frame cache / playback window ------------------------------------------
# How many hourly frames to precompute at startup (the default "pulse" window).
PRELOAD_FRAMES = int(os.getenv("GRID_PRELOAD_FRAMES", "48"))
# Index of the first frame to preload (0 = first snapshot of the year).
PRELOAD_START = int(os.getenv("GRID_PRELOAD_START", "0"))
# Max frames held in the lazy LRU cache.
FRAME_CACHE_SIZE = int(os.getenv("GRID_FRAME_CACHE_SIZE", "800"))

# --- Alert thresholds (single source of truth) ------------------------------
# Line loading (% of thermal rating).
LINE_LOADING_WARN = float(os.getenv("GRID_LINE_LOADING_WARN", "75"))
LINE_LOADING_ALERT = float(os.getenv("GRID_LINE_LOADING_ALERT", "90"))
# Bus voltage is judged against each bus's OWN rated band (min_vm_pu/max_vm_pu
# from the dataset). A breach of the rated band is an alert; coming within this
# per-unit margin of either limit is a warning. (This dataset runs near its
# upper rated limit, so a global fixed band would be meaningless.)
VOLTAGE_WARN_MARGIN = float(os.getenv("GRID_VOLTAGE_WARN_MARGIN", "0.01"))

# --- N-1 security analysis ---------------------------------------------------
# A contingency is "critical" if it pushes any monitored element above this %.
N1_OVERLOAD_PCT = float(os.getenv("GRID_N1_OVERLOAD_PCT", "100"))
N1_MAX_CONTINGENCIES = int(os.getenv("GRID_N1_MAX_CONTINGENCIES", "200"))

# --- Geographic projection (schematic x/y -> WGS84 over California) ---------
# Each NREL-118 region (r1/r2/r3) projects into the real-world bounding box
# of its actual utility service territory (per the NREL paper, Table VIII):
#   r1 = PG&E Bay Area (PGEB)  — 9-county SF Bay Area
#   r2 = SMUD                  — Sacramento county
#   r3 = SDG&E                 — San Diego county
# Format: region_id -> (lon_min, lon_max, lat_min, lat_max).
REGION_TARGETS: dict[str, tuple[float, float, float, float]] = {
    "r1": (-122.45, -121.35, 37.35, 38.15),  # PG&E Bay Area (east of Pacific coast)
    "r2": (-121.55, -121.10, 38.45, 38.78),  # SMUD (Sacramento county, inland)
    "r3": (-117.25, -116.35, 32.65, 33.40),  # SDG&E (San Diego county, east of coast)
}

# Map envelope — full California so the state is visible around the three
# tightly-localized clusters. Used by /api/meta for the initial map fit.
LON_MIN, LON_MAX = -124.5, -114.0
LAT_MIN, LAT_MAX = 32.4, 42.05

# --- AI / chatbot (OpenAI-compatible endpoint, e.g. OpenRouter) -------------
# Uses the OpenAI SDK pointed at any compatible base URL.
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://openrouter.ai/api/v1")
AI_API_KEY = os.getenv("AI_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))
AI_MODEL = os.getenv("AI_MODEL", "anthropic/claude-sonnet-4.5")

# --- Weather (Open-Meteo, no key) -------------------------------------------
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
