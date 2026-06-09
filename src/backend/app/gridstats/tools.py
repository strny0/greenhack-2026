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


# (metric -> (dataframe attr, column)); "line_loading" handled specially.
_TREND_METRICS = {
    "load": ("realtime", "load_mw"),
    "generation": ("realtime", "gen_total_mw"),
    "solar": ("realtime", "solar_mw"),
    "wind": ("realtime", "wind_mw"),
    "max_loading": ("metrics", "max_line_loading_pct"),
    "slack": ("metrics", "slack_mw"),
    "line_loading": None,  # uses branch_loadings[element_id]
}

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# granularity -> (pandas index attribute, label fn, expected bucket count or None)
_GRANULARITIES = {
    "month": ("month", lambda i: _MONTHS[i - 1]),
    "week": ("isocalendar", lambda i: f"W{i:02d}"),  # special-cased below
    "hour_of_day": ("hour", lambda i: f"{i:02d}h"),
    "dow": ("dayofweek", lambda i: _DOW[i]),
}


def long_term_trends(
    metric: str,
    element_id: str | None = None,
    granularity: str = "month",
    current_ts: str | None = None,
) -> dict:
    """Compact long-term/seasonal trend of a grid metric over the full year.

    Reads the precomputed full-year gridstats bundle (instant, no re-solve) and
    buckets one metric by month/week/hour-of-day/day-of-week.

    metric ∈ {load, generation, solar, wind, max_loading, slack, line_loading}
      (line_loading needs element_id = a branch id).
    granularity ∈ {month, week, hour_of_day, dow}.
    current_ts: viewed hour, to locate "now" in the year's distribution.
    Returns {metric, element_id, granularity, unit, span, buckets, overall, trend}.
    Errors return {"error": "..."} (never raises).
    """
    import numpy as np
    import pandas as pd

    if metric not in _TREND_METRICS:
        return {"error": f"unknown metric '{metric}'. Choose one of {sorted(_TREND_METRICS)}."}
    if granularity not in _GRANULARITIES:
        return {"error": f"unknown granularity '{granularity}'. Choose one of {sorted(_GRANULARITIES)}."}

    b = _gs().bundle
    unit = "%" if metric in ("max_loading", "line_loading") else "MW"

    if metric == "line_loading":
        if not element_id:
            return {"error": "metric 'line_loading' requires an element_id (a branch id)."}
        if element_id not in b.branch_loadings.columns:
            return {"error": f"unknown element_id '{element_id}'. Not a branch in the bundle."}
        series = b.branch_loadings[element_id]
    else:
        attr, col = _TREND_METRICS[metric]
        df = getattr(b, attr)
        if col not in df.columns:
            return {"error": f"column '{col}' missing from bundle.{attr}."}
        series = df[col]

    series = pd.to_numeric(series, errors="coerce").dropna()
    if series.empty:
        return {"error": f"no data for metric '{metric}'."}

    idx = series.index
    if granularity == "week":
        keys = idx.isocalendar().week.to_numpy()
        label_fn = lambda i: f"W{int(i):02d}"
    else:
        key_attr, label_fn = _GRANULARITIES[granularity]
        keys = getattr(idx, key_attr)

    grouped = series.groupby(keys)
    buckets = []
    for k, vals in grouped:
        buckets.append({
            "bucket": label_fn(int(k)),
            "mean": round(float(vals.mean()), 1),
            "p95": round(float(vals.quantile(0.95)), 1),
            "max": round(float(vals.max()), 1),
        })

    overall = {
        "mean": round(float(series.mean()), 1),
        "min": round(float(series.min()), 1),
        "max": round(float(series.max()), 1),
        "current": None,
        "current_pct_rank": None,
    }

    if current_ts:
        cur_val = _value_at(series, current_ts)
        if cur_val is not None:
            overall["current"] = round(float(cur_val), 1)
            overall["current_pct_rank"] = int(round(float((series <= cur_val).mean()) * 100))

    # trend = sign of least-squares slope across monthly means over the year.
    monthly = series.groupby(idx.month).mean()
    trend = "flat"
    if len(monthly) >= 2:
        x = np.asarray(monthly.index, dtype=float)
        y = monthly.to_numpy(dtype=float)
        slope = float(np.polyfit(x, y, 1)[0])
        scale = abs(float(series.mean())) or 1.0
        # treat a slope smaller than ~0.5% of the mean per month as flat.
        if slope > 0.005 * scale:
            trend = "rising"
        elif slope < -0.005 * scale:
            trend = "falling"

    return {
        "metric": metric,
        "element_id": element_id if metric == "line_loading" else None,
        "granularity": granularity,
        "unit": unit,
        "span": f"{idx[0].date()} .. {idx[-1].date()}",
        "buckets": buckets,
        "overall": overall,
        "trend": trend,
    }


def _value_at(series, ts: str):
    """Value of a series at the hour nearest ``ts``; None if out of range."""
    import pandas as pd

    try:
        t = pd.Timestamp(ts)
    except (ValueError, TypeError):
        return None
    if t < series.index[0] or t > series.index[-1]:
        return None
    pos = series.index.get_indexer([t], method="nearest")[0]
    if pos < 0:
        return None
    return series.iloc[pos]


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
