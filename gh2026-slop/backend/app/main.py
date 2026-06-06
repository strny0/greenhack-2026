"""Grid Pulse FastAPI backend.

Exposes the canonical grid model + load flow, alerts, time-series, N-1 security
analysis, what-if scenarios, weather overlay, and a dispatcher chatbot proxy.
"""
from __future__ import annotations

import warnings

warnings.filterwarnings("ignore")

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from . import config, engine, weather  # noqa: E402
from .agent import SUGGESTED_QUESTIONS, stream_agent  # noqa: E402
from .chat import chat  # noqa: E402  (legacy one-shot grounded chat)
from .data_loader import store  # noqa: E402
from .model import StateFrame, WhatIfRequest, WhatIfResponse  # noqa: E402

app = FastAPI(title="Grid Pulse API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- gridstats (precomputed deviation timeline + statistical insights) -------
# Lazy process-wide facade over the precomputed bundle. Loading it is just parquet
# reads (no pandapower); a missing bundle degrades to a clear 503 rather than a crash.
_gs_singleton = None


def _gridstats():
    global _gs_singleton
    if _gs_singleton is None:
        from .gridstats import GridStats

        _gs_singleton = GridStats.load()
    return _gs_singleton


@app.on_event("startup")
def _startup() -> None:
    n = engine.preload(config.PRELOAD_START, config.PRELOAD_FRAMES)
    print(f"[grid-pulse] preloaded {n} frames; {len(store.timestamps)} snapshots available")
    # Warm the gridstats bundle so the first /api/deviation/timeline isn't slow.
    # Non-fatal: the deviation endpoints surface a 503 if the bundle isn't built.
    try:
        gs = _gridstats()
        print(f"[grid-pulse] gridstats bundle loaded; {len(gs.deviation_timeline())} deviation hours")
    except Exception as exc:  # noqa: BLE001
        print(f"[grid-pulse] gridstats bundle unavailable ({exc}); run `python -m app.gridstats.build`")


# --- meta --------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "snapshots": len(store.timestamps)}


@app.get("/api/meta")
def meta() -> dict:
    return {
        "count": len(store.timestamps),
        "timestamps": store.timestamps,
        "default_window": {"start": config.PRELOAD_START, "count": config.PRELOAD_FRAMES},
        "bbox": {
            "lon_min": config.LON_MIN,
            "lon_max": config.LON_MAX,
            "lat_min": config.LAT_MIN,
            "lat_max": config.LAT_MAX,
        },
        "sld_coords": store.bus_sld,
        "sld_bbox": store.sld_bbox,
        "thresholds": {
            "line_loading_warn": config.LINE_LOADING_WARN,
            "line_loading_alert": config.LINE_LOADING_ALERT,
            "voltage_warn_margin": config.VOLTAGE_WARN_MARGIN,
            "n1_overload_pct": config.N1_OVERLOAD_PCT,
        },
        "suggested_questions": SUGGESTED_QUESTIONS,
        "engine": "pandapower",
    }


# --- frames ------------------------------------------------------------------


@app.get("/api/frame", response_model=StateFrame)
def frame(timestamp: str = Query(...)) -> StateFrame:
    if not store.timestamps:
        raise HTTPException(503, "No data loaded")
    return engine.base_frame(timestamp)


@app.get("/api/window", response_model=list[StateFrame])
def window(
    start: int = Query(0, ge=0), count: int = Query(24, ge=1, le=200)
) -> list[StateFrame]:
    tss = store.timestamps[start : start + count]
    return [engine.base_frame(ts) for ts in tss]


@app.get("/api/alerts")
def alerts(timestamp: str = Query(...)) -> dict:
    frame = engine.base_frame(timestamp)
    return {"timestamp": frame.timestamp, "alerts": engine.build_alerts(frame)}


@app.get("/api/timeseries")
def timeseries(
    element_id: str = Query(...),
    kind: str = Query("line", pattern="^(line|node)$"),
    metric: str = Query("loading"),
    start: str = Query(...),
    count: int = Query(48, ge=2, le=200),
) -> dict:
    return engine.element_timeseries(element_id, kind, metric, start, count)


# --- security / what-if ------------------------------------------------------


@app.get("/api/n1")
def n1(timestamp: str = Query(...), limit: int = Query(60, ge=1, le=200)) -> dict:
    results = engine.run_n1(timestamp, limit=limit)
    return {
        "timestamp": store.nearest_timestamp(timestamp),
        "n_analyzed": len(results),
        "results": results,
    }


@app.post("/api/whatif", response_model=WhatIfResponse)
def whatif(req: WhatIfRequest) -> WhatIfResponse:
    return engine.run_whatif(req)


# --- weather -----------------------------------------------------------------


@app.get("/api/weather")
async def weather_endpoint(timestamp: str | None = Query(None)) -> dict:
    return await weather.weather_overlay(timestamp)


# --- forecast-vs-actual deviation triage -------------------------------------


@app.get("/api/deviation/timeline")
def deviation_timeline() -> dict:
    """Whole-dataset deterministic deviation-risk timeline (one record per hour).

    Served from the precomputed gridstats bundle — no pandapower solve, no LLM.
    The frontend loads this once and indexes it by timestamp to drive the live
    tier while scrubbing and the history-so-far risk ribbon.
    """
    try:
        gs = _gridstats()
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"records": gs.deviation_timeline(), "built_at": gs.bundle.built_at}


@app.get("/api/deviation/triage")
def deviation_triage(timestamp: str = Query(...)) -> dict:
    """Finest-granularity deviation assessment for ONE hour (on settle).

    Runs ``engine.assess_deviation`` — a real AC solve (LRU-cached) yielding the
    per-generator worst deviations (with bus), active breaches, and conditional
    N-1. The deterministic core only; the LLM verdict comes via /api/agent/stream.
    Called only when the operator settles on an hour, never during scrubbing.
    """
    if not store.timestamps:
        raise HTTPException(503, "No data loaded")
    return engine.assess_deviation(timestamp)


# --- chatbot -----------------------------------------------------------------


class ChatRequest(BaseModel):
    messages: list[dict]
    timestamp: str
    selection: dict | None = None  # {kind: "node"|"line", id} the operator has selected


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest) -> dict:
    """Legacy one-shot grounded chat (kept for reference / fallback)."""
    return await chat(req.messages, req.timestamp)


# --- agentic harness ---------------------------------------------------------


@app.post("/api/agent/stream")
async def agent_stream(req: ChatRequest) -> StreamingResponse:
    """Tool-calling dispatcher agent. Streams NDJSON events (text deltas, tool
    calls, tool results) consumed by the assistant-ui custom runtime."""
    return StreamingResponse(
        stream_agent(req.messages, req.timestamp, req.selection),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- static frontend (single-origin deploy) ----------------------------------
# Serve the built Vite bundle so one uvicorn process answers both /api/* and the
# SPA. Mounted last so it only catches paths not claimed by an /api route above.
# No-op in dev (vite serves the frontend on :5173 and proxies /api here).
from pathlib import Path  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
