"""Whole-dataset deterministic deviation-risk timeline (one row per hour).

This is the cheap, always-on screening layer behind the "continuous deviation
evaluation": for every hour of the year it scores how far the realised system
drifted from the day-ahead plan and how stressed the grid was, and folds that
into a coarse ``risk_tier`` — with NO pandapower solve and NO LLM. It reuses the
already-built :class:`GridStatsBundle` (system-level DA plan vs. actual solar/wind,
``converged``/``slack_mw``/``max_line_loading_pct``/``n_overloaded_lines`` per hour,
de-biased ``surprise_series``), so it is pure vectorised pandas.

The frontend loads this once and indexes it by timestamp to drive the live tier
while scrubbing and the history-so-far risk ribbon. It is a SCREEN, not the final
word: the tier here uses ``n_overloaded_lines`` (lines ≥ ``LINE_LOADING_ALERT``) as
a proxy for the engine's full ``active_breaches`` list and cannot see voltage
breaches. The authoritative, finest-granularity assessment for a single focused
hour is ``engine.assess_deviation`` (per-generator, real breaches, conditional N-1),
which the UI calls on demand when the operator settles on an hour.

The tier logic mirrors what the agent honours (see backend ``engine.assess_deviation``
/ ``forecast_deviation_triage``) so the precomputed ribbon never contradicts the
on-settle triage.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import config
from .stats import GridStatsBundle, surprise_series


def _num(v, default: float = 0.0) -> float:
    """Coerce a possibly-NaN/None cell to a finite float."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _force_signals(
    converged: bool, n_overloaded: int, slack_mw: float, total_load_mw: float
) -> tuple[bool, list[str]]:
    """Deterministic safety-net floor — mirrors engine.assess_deviation.safety_net.

    Returns (force_notify, reasons). Uses n_overloaded_lines as a screening proxy
    for the engine's alert-severity breach list (voltage breaches are not visible
    from the bundle, so this errs toward NOT flagging on voltage — the on-settle
    assessment catches those).
    """
    reasons: list[str] = []
    if not converged:
        reasons.append("load flow did not converge")
    if n_overloaded > 0:
        reasons.append(
            f"{n_overloaded} line(s) overloaded (≥{config.LINE_LOADING_ALERT:.0f}%)"
        )
    if total_load_mw > 0 and abs(slack_mw) >= config.DEV_SLACK_LOAD_FRACTION * total_load_mw:
        frac = abs(slack_mw) / total_load_mw
        reasons.append(
            f"balancing power {slack_mw:+.0f} MW is {frac:.0%} of load "
            f"(≥{config.DEV_SLACK_LOAD_FRACTION:.0%})"
        )
    return (len(reasons) > 0, reasons)


def _significant(solar_delta_mw: float, wind_delta_mw: float) -> bool:
    """Renewable-only significance gate — matches DEV_SOLAR_MW / DEV_WIND_MW."""
    return (
        abs(solar_delta_mw) >= config.DEV_SOLAR_MW
        or abs(wind_delta_mw) >= config.DEV_WIND_MW
    )


def _risk_tier(
    force_notify: bool,
    grid_stressed: bool,
    significant: bool,
    renew_z: float,
) -> str:
    """none | low | medium | high — deterministic, NO LLM.

    Ordering mirrors what the agent honours so the live tier and the on-settle
    triage agree: a forced safety-net breach is always ``high``; a stressed grid
    is at least ``medium``; a renewable miss is ``medium`` only when it is both
    MW-significant AND statistically surprising (|z| ≥ DEV_Z_MED), else ``low`` when
    the de-biased renewable surprise is ≥ DEV_Z_LOW; otherwise ``none``. Advisory
    load never sets the tier (its DA forecast is structurally divergent).

    ``renew_z`` is max(|solar_z|, |wind_z|) — the de-biased renewable surprise.
    """
    if force_notify:
        return "high"
    if grid_stressed:
        return "medium"
    if significant and renew_z >= config.DEV_Z_MED:
        return "medium"
    if renew_z >= config.DEV_Z_LOW:
        return "low"
    return "none"


def _headline_and_where(
    converged: bool,
    force_reasons: list[str],
    grid_stressed: bool,
    max_line_loading_pct: float,
    solar_delta_mw: float,
    wind_delta_mw: float,
    solar_z: float,
    wind_z: float,
) -> tuple[str, str]:
    """Terse operator string + dominant driver (solar|wind|grid).

    Advisory load is deliberately NOT a candidate driver — the tier never reflects
    it, so a load-dominated headline would mislead. The headline reflects whatever
    actually set the tier: a grid breach, or the larger renewable surprise.
    """
    # Convergence failure dominates everything.
    if not converged:
        return ("load flow did not converge", "grid")

    # Candidate driver magnitudes, normalised to be comparable.
    grid_mag = max_line_loading_pct / config.LINE_LOADING_ALERT if grid_stressed else 0.0
    cands = {
        "grid": grid_mag,
        "wind": abs(wind_z),
        "solar": abs(solar_z),
    }
    where = max(cands, key=lambda k: cands[k])
    if cands[where] <= 0.0:
        return ("on plan", where)

    if where == "grid":
        n = ""
        for r in force_reasons:
            if "overloaded" in r:
                n = " — " + r
                break
        return (f"line loading {max_line_loading_pct:.0f}%{n}", "grid")
    if where == "wind":
        return (f"wind {wind_delta_mw:+.0f} MW ({wind_z:+.1f}σ)", "wind")
    return (f"solar {solar_delta_mw:+.0f} MW ({solar_z:+.1f}σ)", "solar")


def deviation_timeline(gs: GridStatsBundle) -> pd.DataFrame:
    """Per-hour deterministic deviation-risk table over the whole dataset.

    Pure vectorised pandas over the bundle (no snapshot reads, no pandapower).
    Indexed by the bundle's metrics index; columns are the per-hour record fields
    documented in this module / served by ``timeline_records``.
    """
    m = gs.metrics
    fc = gs.forecast.reindex(m.index)
    rt = gs.realtime.reindex(m.index)
    z = surprise_series(gs).reindex(m.index)

    solar_delta = (rt.get("solar_mw") - fc.get("solar_mw")).fillna(0.0)
    wind_delta = (rt.get("wind_mw") - fc.get("wind_mw")).fillna(0.0)
    solar_z = z.get("solar", pd.Series(0.0, index=m.index)).fillna(0.0)
    wind_z = z.get("wind", pd.Series(0.0, index=m.index)).fillna(0.0)
    load_z = z.get("load", pd.Series(0.0, index=m.index)).fillna(0.0)

    rows: list[dict] = []
    for ts in m.index:
        converged = bool(m.at[ts, "converged"]) if "converged" in m.columns else True
        n_over = int(_num(m.at[ts, "n_overloaded_lines"])) if "n_overloaded_lines" in m.columns else 0
        slack = _num(m.at[ts, "slack_mw"]) if "slack_mw" in m.columns else 0.0
        load_total = _num(m.at[ts, "total_load_mw"]) if "total_load_mw" in m.columns else 0.0
        max_load = _num(m.at[ts, "max_line_loading_pct"]) if "max_line_loading_pct" in m.columns else 0.0

        sd = _num(solar_delta.at[ts])
        wd = _num(wind_delta.at[ts])
        sz = _num(solar_z.at[ts])
        wz = _num(wind_z.at[ts])
        lz = _num(load_z.at[ts])

        force_notify, force_reasons = _force_signals(converged, n_over, slack, load_total)
        significant = _significant(sd, wd)
        grid_stressed = (max_load >= config.LINE_LOADING_WARN) or (n_over > 0) or (not converged)
        renew_z = max(abs(sz), abs(wz))  # advisory load excluded from the tier

        tier = _risk_tier(force_notify, grid_stressed, significant, renew_z)

        # score in [0,1] for ribbon intensity (1.0 when forced). Renewable surprise
        # vs DEV_Z_MED and grid loading vs the alert level; load is not a driver.
        if force_notify:
            score = 1.0
        else:
            score = max(renew_z / config.DEV_Z_MED, max_load / config.LINE_LOADING_ALERT)
            score = min(max(score, 0.0), 1.0)

        headline, where = _headline_and_where(
            converged, force_reasons, grid_stressed, max_load, sd, wd, sz, wz,
        )

        rows.append({
            "ts": ts.isoformat(),
            "risk_tier": tier,
            "score": round(score, 3),
            "significant": significant,
            "force_notify": force_notify,
            "force_reasons": force_reasons,
            "solar_delta_mw": round(sd, 1),
            "wind_delta_mw": round(wd, 1),
            "solar_z": round(sz, 2),
            "wind_z": round(wz, 2),
            "load_z": round(lz, 2),
            "max_line_loading_pct": round(max_load, 1),
            "slack_mw": round(slack, 1),
            "converged": converged,
            "headline": headline,
            "where": where,
        })

    df = pd.DataFrame(rows).set_index(pd.Index(m.index, name="ts_idx"))
    # store force_reasons as a JSON-ready list — parquet handles object lists fine.
    return df


def _coerce(v):
    """Make a cell JSON-serialisable: numpy arrays → lists, numpy scalars → python."""
    if isinstance(v, np.ndarray):
        return [_coerce(x) for x in v.tolist()]
    if isinstance(v, (list, tuple)):
        return [_coerce(x) for x in v]
    if isinstance(v, np.generic):
        return v.item()
    return v


def records_from_frame(df: pd.DataFrame) -> list[dict]:
    """A deviation-timeline DataFrame as JSON-ready per-hour records.

    Robust to a parquet round-trip, which turns the ``force_reasons`` list column
    into a numpy ``ndarray`` and bool/float columns into numpy scalars — all coerced
    back to plain python so FastAPI can serialise them.
    """
    recs = df.reset_index(drop=True).to_dict(orient="records")
    return [{k: _coerce(v) for k, v in r.items()} for r in recs]


def timeline_records(gs: GridStatsBundle) -> list[dict]:
    """``deviation_timeline`` as a JSON-ready list of per-hour records."""
    return records_from_frame(deviation_timeline(gs))
