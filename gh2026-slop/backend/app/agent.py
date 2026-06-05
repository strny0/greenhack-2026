"""Agentic dispatcher harness (Pydantic AI).

Where `chat.py` did a single grounded completion, this runs a real tool-calling
agent loop: the model reasons, calls read-only tools against the live grid
engine / dataset, and streams its work back token-by-token.

The harness is deliberately model-agnostic — it talks to any OpenAI-compatible
endpoint (OpenRouter, e-infra, vLLM, …) configured via AI_BASE_URL / AI_MODEL.

Tools here are all *read-only* (query the grid). UI-driving tools (focus the
map, change the time, open a panel) are intentionally NOT here yet — they slot
into the same registry later as `@agent.tool` functions whose effects are
emitted as `ui-action` stream events.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import AsyncIterator

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelRequest,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits

from . import config, engine, weather
from .data_loader import store
from .model import WhatIfRequest

# `OpenAIChatModel` is the chat-completions class (works with third-party
# OpenAI-compatible gateways); older versions name it `OpenAIModel`.
try:  # pragma: no cover - version shim
    from pydantic_ai.models.openai import OpenAIChatModel as _OpenAIModel
except ImportError:  # pragma: no cover
    from pydantic_ai.models.openai import OpenAIModel as _OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider

SYSTEM_PROMPT = """You are the dispatcher agent for "Grid Pulse", a real-time \
situational-awareness tool for a transmission system operator (TSO). You help a \
control-room operator understand the current state of the power grid.

You have TOOLS that query the live grid model (a solved AC load flow for the hour \
the operator is currently viewing). Use them — never invent numbers.

Working style:
- Decide which tool(s) answer the question, call them, then summarise.
- Be concise and operational: lead with the answer, then a one-line reason.
- Use line/bus identifiers exactly as the tools return them.
- N-1 and what-if tools re-solve the load flow and are slower — use them only when \
the question is about contingencies or operator actions, and keep limits modest.
- Round sensibly, flag uncertainty, and state clearly when the data does not \
support an answer.
- You are read-only: you advise, you do not switch equipment."""

SUGGESTED_QUESTIONS = [
    "What is the overall state of the grid right now?",
    "Which lines are the most heavily loaded, and why?",
    "Are there any active alerts or voltage problems?",
    "If the busiest line tripped, what would happen?",
    "Show me the loading trend of the most-loaded line.",
]


# --- agent dependencies ------------------------------------------------------


@dataclass
class Deps:
    """Per-request context. `timestamp` is the hour the operator is viewing."""

    timestamp: str


def _model():
    provider = OpenAIProvider(base_url=config.AI_BASE_URL, api_key=config.AI_API_KEY)
    return _OpenAIModel(config.AI_MODEL, provider=provider)


agent: Agent[Deps, str] = Agent(
    _model() if config.AI_API_KEY else "test",
    deps_type=Deps,
    system_prompt=SYSTEM_PROMPT,
    model_settings=ModelSettings(temperature=0.2, max_tokens=900),
)


# --- tools (all read-only) ---------------------------------------------------


def _line_brief(l) -> dict:
    return {
        "id": l.id,
        "from": l.from_node,
        "to": l.to_node,
        "kind": l.kind,
        "loading_pct": l.loading_pct,
        "p_from_mw": l.p_from_mw,
        "in_service": l.in_service,
        "state": l.state,
    }


def _node_brief(n) -> dict:
    return {
        "id": n.id,
        "type": n.type,
        "zone": n.zone,
        "v_nominal_kv": n.v_nominal_kv,
        "vm_pu": n.vm_pu,
        "production_mw": n.production_mw,
        "consumption_mw": n.consumption_mw,
        "net_mw": n.net_mw,
        "state": n.state,
    }


@agent.tool
def grid_summary(ctx: RunContext[Deps]) -> dict:
    """System-wide summary for the hour being viewed: generation, load, balancing
    power, losses, max line loading, and alert/warning counts."""
    f = engine.base_frame(ctx.deps.timestamp)
    s = f.summary
    return {
        "timestamp": f.timestamp,
        "converged": s.converged,
        "total_generation_mw": s.total_generation_mw,
        "total_load_mw": s.total_load_mw,
        "external_balancing_mw": s.slack_mw,
        "losses_mw": s.losses_mw,
        "max_line_loading_pct": s.max_loading_pct,
        "n_alerts": s.n_alerts,
        "n_warnings": s.n_warnings,
        "n_buses": len(f.nodes),
        "n_branches": len(f.lines),
    }


@agent.tool
def most_loaded_lines(ctx: RunContext[Deps], limit: int = 8) -> list[dict]:
    """The most heavily loaded branches (lines + transformers), highest first.
    `limit` caps how many are returned (1-30)."""
    limit = max(1, min(limit, 30))
    f = engine.base_frame(ctx.deps.timestamp)
    ranked = sorted(
        (l for l in f.lines if l.loading_pct is not None),
        key=lambda l: -l.loading_pct,
    )[:limit]
    return [_line_brief(l) for l in ranked]


@agent.tool
def line_detail(ctx: RunContext[Deps], line_id: str) -> dict:
    """Full live values for one branch by its id/name (line or transformer)."""
    f = engine.base_frame(ctx.deps.timestamp)
    l = next((x for x in f.lines if x.id == line_id), None)
    if l is None:
        return {"error": f"No branch '{line_id}'. Use most_loaded_lines to list ids."}
    return {**_line_brief(l), "p_to_mw": l.p_to_mw, "i_ka": l.i_ka, "max_i_ka": l.max_i_ka}


@agent.tool
def node_detail(ctx: RunContext[Deps], node_id: str) -> dict:
    """Full live values for one bus/substation by its id/name."""
    f = engine.base_frame(ctx.deps.timestamp)
    n = next((x for x in f.nodes if x.id == node_id), None)
    if n is None:
        return {"error": f"No bus '{node_id}'."}
    return {
        **_node_brief(n),
        "is_slack": n.is_slack,
        "min_vm_pu": n.min_vm_pu,
        "max_vm_pu": n.max_vm_pu,
        "vm_kv": n.vm_kv,
    }


@agent.tool
def active_alerts(ctx: RunContext[Deps], limit: int = 15) -> list[dict]:
    """Active alerts and warnings (overloaded lines, out-of-band voltages),
    most severe first."""
    f = engine.base_frame(ctx.deps.timestamp)
    alerts = engine.build_alerts(f)[: max(1, min(limit, 50))]
    return [
        {
            "severity": a.severity,
            "category": a.category,
            "element_kind": a.element_kind,
            "element_id": a.element_id,
            "message": a.message,
            "value": a.value,
        }
        for a in alerts
    ]


@agent.tool
def element_history(
    ctx: RunContext[Deps],
    element_id: str,
    kind: str = "line",
    metric: str = "loading",
    count: int = 24,
) -> dict:
    """Recent time-series for one element, starting at the viewed hour.

    kind="line" -> metric in {loading, p_from}; kind="node" -> metric in
    {vm_pu, production, consumption, net}. `count` is the number of hourly points
    (2-72)."""
    if kind not in ("line", "node"):
        return {"error": "kind must be 'line' or 'node'"}
    count = max(2, min(count, 72))
    return engine.element_timeseries(
        element_id, kind, metric, ctx.deps.timestamp, count
    )


@agent.tool
def n1_contingency_analysis(ctx: RunContext[Deps], limit: int = 30) -> dict:
    """Deterministic N-1 security analysis: trip each in-service line, re-solve
    the load flow, and rank by worst resulting stress. Non-converging trips mean
    islanding / voltage collapse (most critical). Slow — keep `limit` small
    (1-60). Returns the worst contingencies."""
    limit = max(1, min(limit, 60))
    results = engine.run_n1(ctx.deps.timestamp, limit=limit)
    return {
        "n_analyzed": len(results),
        "worst": [
            {
                "tripped": r.contingency_name,
                "converged": r.converged,
                "max_loading_pct": r.max_loading_pct,
                "n_overloads": r.n_overloads,
                "overloaded": r.overloaded[:5],
            }
            for r in results[:12]
        ],
    }


@agent.tool
def what_if(
    ctx: RunContext[Deps],
    disconnect_lines: list[str] | None = None,
    trip_nodes: list[str] | None = None,
    load_scale: float = 1.0,
) -> dict:
    """Apply operator actions and re-solve a real load flow: disconnect lines,
    trip buses (drop their gens/loads), and/or scale all load by `load_scale`.
    Returns the base vs scenario max loading, biggest movers, and new alerts."""
    req = WhatIfRequest(
        timestamp=ctx.deps.timestamp,
        disconnect_lines=disconnect_lines or [],
        trip_nodes=trip_nodes or [],
        load_scale=load_scale,
    )
    r = engine.run_whatif(req)
    return {
        "converged": r.scenario.summary.converged,
        "base_max_loading_pct": r.base.summary.max_loading_pct,
        "scenario_max_loading_pct": r.scenario.summary.max_loading_pct,
        "biggest_movers": r.diffs[:8],
        "new_alerts": [
            {"element_id": a.element_id, "message": a.message} for a in r.new_alerts
        ],
    }


@agent.tool_plain
async def weather_overlay() -> dict:
    """Live cloud cover & wind (Open-Meteo) at the largest solar hubs, with a
    labelled (non-ML) solar-drop heuristic. May be unavailable offline."""
    try:
        data = await weather.weather_overlay(None)
        return {"summary": data.get("summary"), "points": data.get("points", [])[:8]}
    except Exception as e:  # noqa: BLE001
        return {"error": f"weather unavailable: {e}"}


# --- streaming runner --------------------------------------------------------


def _to_history(messages: list[dict]):
    """Convert the frontend [{role, content}] log (minus the final user turn)
    into pydantic-ai message history."""
    history = []
    for m in messages:
        content = m.get("content") or ""
        if m.get("role") == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        elif m.get("role") == "assistant":
            history.append(ModelResponse(parts=[TextPart(content=content)]))
    return history


def _jsonable(value):
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


async def stream_agent(messages: list[dict], timestamp: str) -> AsyncIterator[str]:
    """Run the agent and yield NDJSON event lines for the frontend runtime.

    Event shapes (one JSON object per line):
      {"type":"text","delta": str}            incremental answer text
      {"type":"reasoning","delta": str}       incremental thinking (if the model emits it)
      {"type":"tool-call","id","name","args"} a tool invocation
      {"type":"tool-result","id","name","result"} its result
      {"type":"error","message"}              fatal error
      {"type":"done"}                         end of turn
    """
    if not config.AI_API_KEY:
        msg = (
            "⚠️ No AI key configured. Set AI_API_KEY (and AI_BASE_URL / AI_MODEL) "
            "in backend/.env to enable the dispatcher agent."
        )
        yield json.dumps({"type": "text", "delta": msg}) + "\n"
        yield json.dumps({"type": "done"}) + "\n"
        return

    ts = store.nearest_timestamp(timestamp)
    deps = Deps(timestamp=ts)
    prompt = ""
    history = messages
    if messages and messages[-1].get("role") == "user":
        prompt = messages[-1].get("content") or ""
        history = messages[:-1]

    try:
        async with agent.iter(
            prompt,
            deps=deps,
            message_history=_to_history(history),
            usage_limits=UsageLimits(request_limit=8),
        ) as run:
            async for node in run:
                if Agent.is_model_request_node(node):
                    async with node.stream(run.ctx) as request_stream:
                        async for event in request_stream:
                            if isinstance(event, PartStartEvent):
                                part = event.part
                                if isinstance(part, TextPart) and part.content:
                                    yield json.dumps(
                                        {"type": "text", "delta": part.content}
                                    ) + "\n"
                                elif isinstance(part, ThinkingPart) and part.content:
                                    yield json.dumps(
                                        {"type": "reasoning", "delta": part.content}
                                    ) + "\n"
                            elif isinstance(event, PartDeltaEvent):
                                d = event.delta
                                if isinstance(d, TextPartDelta) and d.content_delta:
                                    yield json.dumps(
                                        {"type": "text", "delta": d.content_delta}
                                    ) + "\n"
                                elif isinstance(d, ThinkingPartDelta) and d.content_delta:
                                    yield json.dumps(
                                        {"type": "reasoning", "delta": d.content_delta}
                                    ) + "\n"
                elif Agent.is_call_tools_node(node):
                    async with node.stream(run.ctx) as tool_stream:
                        async for event in tool_stream:
                            if isinstance(event, FunctionToolCallEvent):
                                p = event.part
                                args = p.args
                                if isinstance(args, str):
                                    try:
                                        args = json.loads(args) if args else {}
                                    except json.JSONDecodeError:
                                        pass
                                yield json.dumps(
                                    {
                                        "type": "tool-call",
                                        "id": p.tool_call_id,
                                        "name": p.tool_name,
                                        "args": _jsonable(args),
                                    }
                                ) + "\n"
                            elif isinstance(event, FunctionToolResultEvent):
                                res = event.result
                                content = (
                                    res.content if isinstance(res, ToolReturnPart) else res
                                )
                                yield json.dumps(
                                    {
                                        "type": "tool-result",
                                        "id": event.tool_call_id,
                                        "result": _jsonable(content),
                                    }
                                ) + "\n"
    except Exception as e:  # noqa: BLE001
        yield json.dumps({"type": "error", "message": str(e)}) + "\n"
    yield json.dumps({"type": "done"}) + "\n"
