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


@app.on_event("startup")
def _startup() -> None:
    n = engine.preload(config.PRELOAD_START, config.PRELOAD_FRAMES)
    print(f"[grid-pulse] preloaded {n} frames; {len(store.timestamps)} snapshots available")


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
            "lon_min": config.CZ_LON_MIN,
            "lon_max": config.CZ_LON_MAX,
            "lat_min": config.CZ_LAT_MIN,
            "lat_max": config.CZ_LAT_MAX,
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


# --- chatbot -----------------------------------------------------------------


class ChatRequest(BaseModel):
    messages: list[dict]
    timestamp: str


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
        stream_agent(req.messages, req.timestamp),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
