"""Dispatcher chatbot via an OpenAI-compatible endpoint (e.g. OpenRouter).

The grid's current state (frame summary, alerts, most-loaded lines) is injected
as system context so the model can answer operator questions grounded in live
data. Uses the OpenAI SDK pointed at AI_BASE_URL — works with OpenRouter or any
compatible gateway.
"""
from __future__ import annotations

from openai import AsyncOpenAI

from . import config, engine

SYSTEM_PROMPT = """You are the dispatcher assistant for "Grid Pulse", a real-time \
situational-awareness tool for a transmission system operator (TSO). You help a \
control-room operator understand the current state of the grid.

Rules:
- Be concise and operational. Lead with the answer, then a one-line reason.
- Only use the GRID STATE CONTEXT provided below. If something isn't in it, say so \
and suggest running N-1 or a what-if scenario in the UI.
- Use line/bus identifiers exactly as given.
- Never invent numbers. Round sensibly. Flag uncertainty.
- You are read-only: you advise, you do not switch equipment.
"""

SUGGESTED_QUESTIONS = [
    "What is the overall state of the grid right now?",
    "Which lines are the most heavily loaded?",
    "Are there any active alerts or voltage problems?",
    "What is the current generation vs load balance?",
    "If the busiest line tripped, what would happen?",
]


def _context_for(timestamp: str) -> str:
    frame = engine.base_frame(timestamp)
    alerts = engine.build_alerts(frame)
    s = frame.summary
    lines_sorted = sorted(
        (l for l in frame.lines if l.loading_pct is not None),
        key=lambda l: -l.loading_pct,
    )[:8]
    top_lines = "\n".join(
        f"  - {l.name} ({l.from_node}->{l.to_node}, {l.kind}): {l.loading_pct:.0f}% loaded"
        for l in lines_sorted
    )
    alert_txt = (
        "\n".join(f"  - [{a.severity}] {a.message}" for a in alerts[:10])
        or "  (none)"
    )
    return f"""GRID STATE CONTEXT (timestamp {frame.timestamp}):
System summary:
  - Load flow converged: {s.converged}
  - Total generation: {s.total_generation_mw:.0f} MW
  - Total load: {s.total_load_mw:.0f} MW
  - External-grid balancing power: {s.slack_mw:.0f} MW
  - Losses: {s.losses_mw:.0f} MW
  - Max line loading: {s.max_loading_pct:.0f}%
  - Active alerts: {s.n_alerts}, warnings: {s.n_warnings}
  - Buses: {len(frame.nodes)}, branches: {len(frame.lines)}
Most-loaded branches:
{top_lines}
Active alerts/warnings:
{alert_txt}
"""


async def chat(messages: list[dict], timestamp: str) -> dict:
    """messages: [{role, content}]. Returns {reply, model, grounded}."""
    if not config.AI_API_KEY:
        return {
            "reply": (
                "⚠️ No AI key configured. Set AI_API_KEY (and optionally AI_BASE_URL / "
                "AI_MODEL) in backend/.env to enable the dispatcher chatbot. "
                "Meanwhile, here is the grounded grid context:\n\n"
                + _context_for(timestamp)
            ),
            "model": None,
            "grounded": True,
        }

    client = AsyncOpenAI(base_url=config.AI_BASE_URL, api_key=config.AI_API_KEY)
    full_messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": _context_for(timestamp)},
        *messages,
    ]
    try:
        resp = await client.chat.completions.create(
            model=config.AI_MODEL,
            messages=full_messages,
            temperature=0.2,
            max_tokens=600,
        )
        return {
            "reply": resp.choices[0].message.content,
            "model": config.AI_MODEL,
            "grounded": True,
        }
    except Exception as e:  # noqa: BLE001
        return {"reply": f"AI request failed: {e}", "model": config.AI_MODEL, "grounded": False}
