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
# Day-ahead forecast series ("the plan") compared against the solved snapshot.
FORECASTS_DA_SOLAR = FORECASTS_DIR / "DA" / "Solar"  # Solar1..75DA.csv -> solar_001..
FORECASTS_DA_WIND = FORECASTS_DIR / "DA" / "Wind"    # Wind1..17DA.csv  -> wind_001..
FORECASTS_DA_LOAD = FORECASTS_DIR / "DA" / "Load"    # LoadR1..3DA.csv  -> region r1..r3

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

# --- Forecast-vs-actual deviation triage ------------------------------------
# A deviation is "significant" (worth pulling weather / running N-1) when the
# system-level generation gap or any region's load gap crosses these. Tunable.
DEV_SOLAR_MW = float(os.getenv("GRID_DEV_SOLAR_MW", "300"))  # |plan-actual| solar
DEV_WIND_MW = float(os.getenv("GRID_DEV_WIND_MW", "40"))     # |plan-actual| wind
# (Load is advisory only — the DA load forecast is structurally divergent from the
# snapshots here, so it does not gate significance; see engine.assess_deviation.)
# Conditional N-1 only runs when significant/stressed; keep this cap small.
N1_DEV_LIMIT = int(os.getenv("GRID_N1_DEV_LIMIT", "20"))
# Deterministic safety net: balancing power beyond this fraction of total load
# means the slack is doing too much work to mask the deviation -> force notify.
DEV_SLACK_LOAD_FRACTION = float(os.getenv("GRID_DEV_SLACK_LOAD_FRACTION", "0.25"))

# --- Geographic projection (schematic x/y -> WGS84 over Czechia) ------------
# The dataset ships schematic coordinates, not geography. We linearly project
# them into this bounding box so the grid reads as a real map of Czechia.
CZ_LON_MIN = 12.35
CZ_LON_MAX = 18.60
CZ_LAT_MIN = 48.70
CZ_LAT_MAX = 50.90

# --- AI / chatbot (OpenAI-compatible endpoint, e.g. OpenRouter) -------------
# Uses the OpenAI SDK pointed at any compatible base URL.
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://openrouter.ai/api/v1")
AI_API_KEY = os.getenv("AI_API_KEY", os.getenv("OPENROUTER_API_KEY", ""))
AI_MODEL = os.getenv("AI_MODEL", "anthropic/claude-sonnet-4.5")

# --- Weather (Open-Meteo, no key) -------------------------------------------
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
