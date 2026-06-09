"""Grid Pulse FastAPI backend.

Exposes the canonical grid model + load flow, alerts, time-series, N-1 security
analysis, what-if scenarios, weather overlay, and a dispatcher chatbot proxy.
"""
from __future__ import annotations

import json as _json
import warnings

warnings.filterwarnings("ignore")

from fastapi import FastAPI, Header, HTTPException, Query, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from . import config, engine, tracing, weather  # noqa: E402
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


def _default_window() -> dict:
    """Resolve the initial view from config.DEFAULT_VIEW_TS: the window starts at
    that day's first frame and `idx` is the hour offset to land on within it. Falls
    back to the legacy PRELOAD_START index if the configured day isn't in the set."""
    times = store.timestamps
    ts = config.DEFAULT_VIEW_TS
    day = ts[:10]
    start = next((i for i, t in enumerate(times) if t[:10] == day), None)
    if start is None:
        return {"start": config.PRELOAD_START, "count": config.PRELOAD_FRAMES, "idx": 0}
    full = next((i for i, t in enumerate(times) if t == ts), None)
    idx = max(0, full - start) if full is not None else 0
    return {"start": start, "count": config.PRELOAD_FRAMES, "idx": idx}


@app.on_event("startup")
def _startup() -> None:
    dw = _default_window()
    n = engine.preload(dw["start"], dw["count"])
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
        "default_window": _default_window(),
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


class WhatIfWindowRequest(BaseModel):
    start: int
    count: int = 24
    preset: str


@app.post("/api/whatif_window")
def whatif_window_endpoint(req: WhatIfWindowRequest) -> StreamingResponse:
    """Whole-day failure simulation: resolve a preset once at the window start,
    then solve a scenario frame for each hour. Streamed JSON so the frontend can
    show a download/progress bar (mirrors /api/window)."""
    spec, frames = engine.whatif_window(req.start, req.count, req.preset)
    if not spec.feasible:
        raise HTTPException(422, spec.reason or "Scenario not feasible")
    payload = {
        "scenario": spec.model_dump(),
        "frames": [f.model_dump() for f in frames],
    }
    return StreamingResponse(iter([_json.dumps(payload)]), media_type="application/json")


# --- weather -----------------------------------------------------------------


@app.get("/api/weather")
async def weather_endpoint(timestamp: str | None = Query(None)) -> dict:
    return await weather.weather_overlay(timestamp)


# --- chatbot -----------------------------------------------------------------


class ChatRequest(BaseModel):
    messages: list[dict]
    timestamp: str
    selection: dict | None = None  # {kind: "node"|"line", id} the operator has selected
    simulation: dict | None = None  # active failure-simulation ScenarioSpec, if any


@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest) -> dict:
    """Legacy one-shot grounded chat (kept for reference / fallback)."""
    return await chat(req.messages, req.timestamp)


# --- agentic harness ---------------------------------------------------------


@app.post("/api/agent/stream")
async def agent_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    """Tool-calling dispatcher agent. Streams NDJSON events (text deltas, tool
    calls, tool results) consumed by the assistant-ui custom runtime.

    Each turn is appended to the server-side usage log (see app.tracing) so the
    operator can see who used the chat in the deployment."""
    headers = dict(request.headers)
    client_host = request.client.host if request.client else None

    async def traced():
        """Pass the agent's NDJSON straight through while accumulating a compact
        summary (reply text + tool names) to log once the turn ends."""
        reply_parts: list[str] = []
        tools: list[str] = []
        error: str | None = None
        try:
            async for line in stream_agent(
                req.messages, req.timestamp, req.selection, req.simulation
            ):
                try:
                    ev = _json.loads(line)
                    if ev.get("type") == "text":
                        reply_parts.append(str(ev.get("delta", "")))
                    elif ev.get("type") == "tool-call":
                        tools.append(str(ev.get("name", "")))
                    elif ev.get("type") == "error":
                        error = str(ev.get("message"))
                except (ValueError, AttributeError):
                    pass
                yield line
        finally:
            tracing.append(
                tracing.build_record(
                    headers=headers,
                    client_host=client_host,
                    messages=req.messages,
                    timestamp=req.timestamp,
                    selection=req.selection,
                    simulation=req.simulation,
                    reply="".join(reply_parts),
                    tools=tools,
                    error=error,
                )
            )

    return StreamingResponse(
        traced(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- usage tracing (admin) ---------------------------------------------------


def _require_admin(token: str | None) -> None:
    """Gate the trace views on the ADMIN_TOKEN shared secret."""
    if not config.ADMIN_TOKEN:
        raise HTTPException(404, "Tracing admin endpoint is disabled (set GRID_ADMIN_TOKEN).")
    if token != config.ADMIN_TOKEN:
        raise HTTPException(401, "Bad or missing admin token.")


@app.get("/api/admin/traces")
def admin_traces(
    limit: int = Query(200, ge=1, le=5000),
    token: str | None = Query(None),
    x_admin_token: str | None = Header(None),
) -> dict:
    """Recent dispatcher-agent usage. Pass the secret as `?token=` or an
    `X-Admin-Token` header. Returns a usage rollup plus the latest turns."""
    _require_admin(token or x_admin_token)
    return {"stats": tracing.stats(), "traces": tracing.read_recent(limit)}


# --- static frontend (single-origin deploy) ----------------------------------
# Serve the built Vite bundle so one uvicorn process answers both /api/* and the
# SPA. Mounted last so it only catches paths not claimed by an /api route above.
# No-op in dev (vite serves the frontend on :5173 and proxies /api here).
from pathlib import Path  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
