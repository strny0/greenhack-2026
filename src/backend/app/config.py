"""Central configuration: data paths, alert thresholds, AI provider settings.

All operator-tunable knobs live here so they can be changed in one place.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from . import paths

load_dotenv()

# --- Data location -----------------------------------------------------------
# Dataset paths come from the shared single-source-of-truth module (app.paths),
# which both this config and the standalone app.gridstats.* use. DATA_DIR is the
# downloaded/mounted payload (GRID_DATA_DIR); OVERRIDES_DIR is the small,
# version-controlled operator CSVs that ship with the app (GRID_OVERRIDES_DIR).
DATA_DIR = paths.data_dir()
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
STATIC_DIR = DATA_DIR / "static"
FORECASTS_DIR = DATA_DIR / "forecasts"
REALTIME_DIR = DATA_DIR / "realtime"
# Day-ahead forecast series ("the plan") compared against the solved snapshot.
FORECASTS_DA_SOLAR = FORECASTS_DIR / "DA" / "Solar"  # Solar1..75DA.csv -> solar_001..
FORECASTS_DA_WIND = FORECASTS_DIR / "DA" / "Wind"    # Wind1..17DA.csv  -> wind_001..
FORECASTS_DA_LOAD = FORECASTS_DIR / "DA" / "Load"    # LoadR1..3DA.csv  -> region r1..r3
OVERRIDES_DIR = paths.overrides_dir()

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

# --- Chat tracing (server-side usage log) -----------------------------------
# Every dispatcher-agent turn in the deployment is appended to a JSONL file so
# the operator can see whether (and how) visitors used the chat. Off by default
# only if explicitly disabled. The admin view endpoint is gated by ADMIN_TOKEN.
CHAT_TRACING = os.getenv("GRID_CHAT_TRACING", "1") not in ("0", "false", "False", "")
CHAT_TRACE_FILE = Path(
    os.getenv("GRID_CHAT_TRACE_FILE", str(Path(__file__).resolve().parents[1] / "chat_traces.jsonl"))
)
# Shared secret required to read /api/admin/traces. Empty = endpoint disabled.
ADMIN_TOKEN = os.getenv("GRID_ADMIN_TOKEN", "")
