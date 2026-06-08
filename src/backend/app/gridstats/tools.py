"""Agent-facing tool functions (thin, framework-agnostic).

Each function returns a JSON-able **context insert** for the LLM agent. The
docstrings are written FOR the LLM — they become the tool descriptions when the
backend later registers them. These tools are **defined here but NOT registered**
with any agent (no @agent.tool, no edits to agent.py/chat.py).

Tier semantics:
  * Lightweight tools (``explain_hour``, ``plan_adherence``, ``loading_context``)
    take a single timestamp or day and answer most questions cheaply.
  * ``interesting_days`` is the only **range** tool (it scans a date window).
  * ``deep_dive`` is the heavyweight detailed tier — see its warning.

All tools serve from a lazily-loaded default GridStats instance (the precomputed
bundle). The first call loads the bundle; subsequent calls reuse it.
"""
from __future__ import annotations

from . import GridStats

_DEFAULT: GridStats | None = None


def _gs() -> GridStats:
    """Return the process-wide default GridStats, loading the bundle on first use."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = GridStats.load()
    return _DEFAULT


def interesting_days(start_date: str, end_date: str, n: int = 10) -> list[dict]:
    """List the most anomalous grid days in a date range, ranked by severity.

    Use this to answer "which days were unusual / worth looking at" over a window.
    Each returned day has a single clear ``driver`` (load, solar, wind, or loading)
    — the de-biased signal that made it stand out — plus its score and raw context
    (peak loading %, peak load MW). This is the ONLY range tool; for a single hour
    or day use the lightweight tools instead.

    Args:
        start_date: inclusive start, e.g. "2024-09-01".
        end_date:   inclusive end, e.g. "2024-09-30".
        n:          max number of days to return (default 10).
    """
    df = _gs().interesting_days(start_date, end_date, n)
    return _records(df)


def explain_hour(timestamp: str, override=None) -> dict:
    """Explain what was unusual on the grid at a single hour (lightweight).

    Returns system metrics with anomaly z-scores, the de-biased plan deviation
    (σ) per metric (load/solar/wind), the top-3 stressed branches vs their normal
    band, 1-hour momentum, and a ready-to-inject ``summary_text``. This is the
    default tool for "what happened at <time>" questions.

    Args:
        timestamp: ISO hour, e.g. "2024-09-13T18:00:00".
        override: optional scenario actuals (failure simulation) for this hour.
    """
    return _gs().explain_hour(timestamp, override=override)


def plan_adherence(day: str) -> dict:
    """Assess how closely the day matched the day-ahead plan (lightweight).

    Returns, per metric (load/solar/wind), the mean de-biased |σ| over the day and
    the worst hour, plus a short verdict ("on plan" / "off plan: …"). Use this for
    "did <day> go to plan / how off-plan was it" questions.

    Args:
        day: calendar day, e.g. "2024-07-17".
    """
    return _gs().plan_adherence(day)


def loading_context(timestamp: str, top: int = 5, override=None) -> dict:
    """Show the most-loaded branches at an hour vs their normal band (lightweight).

    Returns the top branches by loading at the given hour, each with its p90/p95/p99
    normal band (for this hour-of-day × workday) and an approximate percentile rank.
    Use this for "is this line unusually loaded right now" questions.

    Args:
        timestamp: ISO hour, e.g. "2024-09-13T18:00:00".
        top:       number of branches to return (default 5).
    """
    return _gs().loading_context(timestamp, top, override=override)


def deep_dive(timestamp: str, override=None) -> dict:
    """Exhaustive single-hour breakdown — VERBOSE & EXPENSIVE context.

    Only call when the operator explicitly asks for an in-depth breakdown; the
    lightweight tools answer most questions. Returns ALL metrics raw + z, full
    per-metric plan deviation, ALL stressed branches with thresholds, momentum at
    1h and 24h, and the day's plan-adherence context.

    Args:
        timestamp: ISO hour, e.g. "2024-09-13T18:00:00".
    """
    return _gs().deep_dive(timestamp, override=override)


def _records(df) -> list[dict]:
    """DataFrame → list of JSON-able dicts (index → ``date`` ISO string)."""
    out = []
    for idx, row in df.iterrows():
        rec = {"date": _iso(idx)}
        for k, v in row.items():
            rec[k] = _scalar(v)
        out.append(rec)
    return out


def _iso(idx) -> str:
    try:
        return idx.isoformat()
    except AttributeError:
        return str(idx)


def _scalar(v):
    import numpy as np
    import pandas as pd

    if isinstance(v, (np.floating, np.integer)):
        return v.item()
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v
