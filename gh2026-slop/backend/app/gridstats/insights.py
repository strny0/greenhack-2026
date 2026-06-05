"""Analysis functions operating on a loaded GridStatsBundle.

Everything reads from the bundle (including per-branch loadings, which come from
``gs.branch_loadings`` — NOT from re-reading snapshots). All functions return
JSON-able dicts (timestamps → ISO strings, numpy floats → python floats) with a
``summary_text`` string. Out-of-range timestamps/days return an error dict.

Tiers:
  explain_hour / plan_adherence / loading_context  — lightweight, single hour/day
  interesting_days                                  — the only range tool
  deep_dive                                         — verbose & expensive, single hour
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from .stats import GridStatsBundle, surprise_series

# (metric, forecast column, realtime column) — used by explain/deep_dive deltas
_DELTA_PAIRS = [
    ("solar", "solar_mw",      "solar_mw"),
    ("wind",  "wind_mw",       "wind_mw"),
    ("load",  "load_total_mw", "load_mw"),
]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _bounds(gs: GridStatsBundle) -> tuple[pd.Timestamp, pd.Timestamp]:
    lo = pd.Timestamp(gs.first_ts) if gs.first_ts else gs.metrics.index[0]
    hi = pd.Timestamp(gs.last_ts) if gs.last_ts else gs.metrics.index[-1]
    return lo, hi


def _out_of_range(gs: GridStatsBundle, ts: pd.Timestamp) -> dict | None:
    lo, hi = _bounds(gs)
    if ts < lo or ts > hi:
        return {
            "error": (
                f"{ts.isoformat()} is outside dataset window "
                f"({lo.isoformat()} … {hi.isoformat()})."
            )
        }
    return None


def _nearest_row(df: pd.DataFrame, ts: pd.Timestamp) -> pd.Series:
    if ts in df.index:
        return df.loc[ts]
    idx = df.index.get_indexer([ts], method="nearest")[0]
    return df.iloc[idx]


def _f(x) -> float:
    """numpy/pandas scalar → python float (NaN-safe)."""
    return float(x)


# ---------------------------------------------------------------------------
# interesting_days — the only range tool
# ---------------------------------------------------------------------------

def interesting_days(
    gs: GridStatsBundle,
    start_date: str | None = None,
    end_date: str | None = None,
    n: int = 10,
) -> pd.DataFrame:
    """Rank calendar days in [start_date, end_date] by their biggest de-biased anomaly.

    "Max-of-surprises": each day's score is the largest of four daily |z| signals,
    so a flagged day always has one clear, narratable driver (the ``driver`` column):

      load_surprise_z   — de-biased day-ahead load plan deviation
      solar_surprise_z  — de-biased solar plan deviation
      wind_surprise_z   — de-biased wind plan deviation (the noisiest series)
      loading_z         — max_line_loading anomaly vs its own seasonal pattern (STL)

    The slack series is intentionally dropped (22 MW noise floor → spurious z's).
    Raw context columns (peak_loading_pct, peak_load_mw) are kept so the flag is
    explainable. Returns columns: score, driver, load_surprise_z, solar_surprise_z,
    wind_surprise_z, loading_z, peak_loading_pct, peak_load_mw.
    """
    by_date = lambda s: s.groupby(s.index.date)  # noqa: E731

    daily: dict[str, pd.Series] = {}

    surprise = surprise_series(gs)
    for metric in surprise.columns:
        daily[f"{metric}_surprise_z"] = by_date(surprise[metric].abs()).mean()

    if "max_loading" in gs.residuals.columns:
        std = gs.residual_std.get("max_loading", 1.0) or 1.0
        loading_z = (gs.residuals["max_loading"].abs() / std)
        daily["loading_z"] = by_date(loading_z).mean()

    df = pd.DataFrame(daily)

    df["peak_loading_pct"] = by_date(gs.metrics["max_line_loading_pct"]).max()
    df["peak_load_mw"] = by_date(gs.metrics["total_load_mw"]).max()

    z_cols = [c for c in df.columns if c.endswith("_z")]
    df["score"] = df[z_cols].max(axis=1)
    df["driver"] = (
        df[z_cols].idxmax(axis=1)
        .str.replace("_surprise_z", "", regex=False)
        .str.replace("_z", "", regex=False)
    )

    df.index = pd.to_datetime(df.index)

    if start_date is not None:
        df = df[df.index >= pd.Timestamp(start_date).normalize()]
    if end_date is not None:
        # inclusive of the whole end day
        end = pd.Timestamp(end_date).normalize() + pd.Timedelta(days=1)
        df = df[df.index < end]

    ordered = ["score", "driver"] + z_cols + ["peak_loading_pct", "peak_load_mw"]
    return df[ordered].sort_values("score", ascending=False).head(n)


# ---------------------------------------------------------------------------
# branch stress (from the bundle, not from snapshots)
# ---------------------------------------------------------------------------

def _stressed_branches(
    gs: GridStatsBundle, ts: pd.Timestamp, limit: int | None = None
) -> list[dict]:
    """Branches at/above their p90 (for this hour×workday) at ``ts``.

    Loadings come from ``gs.branch_loadings``; thresholds from the percentile table.
    Sorted by loading desc. ``limit`` caps the count (None = all).
    """
    hour = ts.hour
    is_workday = int(ts.weekday() < 5)
    key = (hour, is_workday)
    out: list[dict] = []
    if key not in gs.branch_pct90.index:
        return out

    pct90_row = gs.branch_pct90.loc[key]
    pct95_row = gs.branch_pct95.loc[key]
    pct99_row = gs.branch_pct99.loc[key]

    row = _nearest_row(gs.branch_loadings, ts)
    actual_loadings: dict[str, float] = {}
    for branch_name, val in row.items():
        if val is None or (isinstance(val, float) and math.isnan(val)):
            continue
        actual_loadings[str(branch_name)] = round(float(val), 1)

    for branch_name, actual in sorted(actual_loadings.items(), key=lambda x: -x[1]):
        if branch_name not in pct90_row.index:
            continue
        thr90 = pct90_row[branch_name]
        if math.isnan(thr90) or actual < thr90:
            continue
        thr99 = pct99_row[branch_name] if branch_name in pct99_row.index else float("nan")
        thr95 = pct95_row[branch_name] if branch_name in pct95_row.index else float("nan")
        pct_rank = 99 if (not math.isnan(thr99) and actual >= thr99) else (
                   95 if (not math.isnan(thr95) and actual >= thr95) else 90)
        out.append({
            "name": branch_name,
            "loading_pct": actual,
            "threshold_90th_pct": round(float(thr90), 1),
            "pct_rank": pct_rank,
        })
        if limit is not None and len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# explain_hour — lightweight single hour
# ---------------------------------------------------------------------------

def explain_hour(gs: GridStatsBundle, timestamp: str) -> dict:
    """Compact LLM context for a single hour.

    System metrics + STL z-scores (slack shown but not ranked), de-biased
    plan-deviation σ per metric, top-3 stressed branches (vs p90), 1h momentum,
    and a ``summary_text`` line. Branch loadings come from the bundle.
    """
    ts = pd.Timestamp(timestamp)
    err = _out_of_range(gs, ts)
    if err is not None:
        return err

    row = _nearest_row(gs.residuals, ts)
    z = {}
    for col in gs.residuals.columns:
        std = gs.residual_std.get(col, 1.0) or 1.0
        z[f"z_{col}"] = round(_f(row[col]) / std, 2)

    m = _nearest_row(gs.metrics, ts)
    system = {
        "total_load_mw":        round(_f(m["total_load_mw"]), 1),
        "total_gen_mw":         round(_f(m["total_gen_mw"]), 1),
        "max_line_loading_pct": round(_f(m["max_line_loading_pct"]), 1),
        "slack_mw":             round(_f(m["slack_mw"]), 1),
        **z,
    }

    fc_deltas = _forecast_deltas(gs, ts)

    # --- momentum (1h) ---
    momentum: dict = {}
    prev_ts = ts - timedelta(hours=1)
    if prev_ts in gs.metrics.index:
        pm = gs.metrics.loc[prev_ts]
        momentum["load_delta_1h_mw"] = round(
            _f(m["total_load_mw"]) - _f(pm["total_load_mw"]), 1
        )
        momentum["loading_delta_1h_pct"] = round(
            _f(m["max_line_loading_pct"]) - _f(pm["max_line_loading_pct"]), 1
        )

    top_branches = _stressed_branches(gs, ts, limit=3)

    # --- summary text ---
    lines = [f"[{ts.isoformat()}]"]
    lines.append(
        f"Load {system['total_load_mw']} MW (z={z.get('z_load', 0):+.1f}), "
        f"max line loading {system['max_line_loading_pct']}% (z={z.get('z_max_loading', 0):+.1f}), "
        f"slack {system['slack_mw']:+.0f} MW (z={z.get('z_slack', 0):+.1f})"
    )
    if fc_deltas:
        parts = []
        for metric, d in fc_deltas.items():
            sz = d.get("surprise_z")
            sz_txt = f", {sz:+.1f}σ" if sz is not None else ""
            parts.append(f"{metric} {d['delta_mw']:+.0f} MW ({d['delta_pct']:+.1f}%{sz_txt})")
        lines.append("Plan deviation (de-biased): " + ", ".join(parts))
    if momentum:
        m1h_load = momentum.get("load_delta_1h_mw")
        m1h_ldg = momentum.get("loading_delta_1h_pct")
        if m1h_load is not None:
            lines.append(f"Trend (1h): load {m1h_load:+.0f} MW, max loading {m1h_ldg:+.1f}%")
    if top_branches:
        names = ", ".join(b["name"] for b in top_branches[:3])
        lines.append(f"Stressed branches (≥90th pct): {names}")

    return {
        "timestamp": ts.isoformat(),
        "system": system,
        "forecast_deltas": fc_deltas,
        "momentum": momentum,
        "top_branches": top_branches,
        "summary_text": "\n".join(lines),
    }


def _forecast_deltas(gs: GridStatsBundle, ts: pd.Timestamp) -> dict:
    """Per-metric forecast/actual/delta + de-biased surprise_z at ``ts``."""
    out: dict = {}
    if ts not in gs.forecast.index or ts not in gs.realtime.index:
        return out
    fc = gs.forecast.loc[ts]
    rt = gs.realtime.loc[ts]
    for metric, fc_col, rt_col in _DELTA_PAIRS:
        if fc_col not in fc.index or rt_col not in rt.index:
            continue
        if pd.isna(fc[fc_col]) or pd.isna(rt[rt_col]):
            continue
        delta_mw = round(_f(rt[rt_col]) - _f(fc[fc_col]), 1)
        base = _f(fc[fc_col]) or 1.0
        entry = {
            "forecast_mw": round(_f(fc[fc_col]), 1),
            "actual_mw":   round(_f(rt[rt_col]), 1),
            "delta_mw":    delta_mw,
            "delta_pct":   round(100 * delta_mw / abs(base), 1),
        }
        bl = gs.forecast_error.get(metric)
        if bl is not None:
            entry["surprise_z"] = round((delta_mw - bl["bias"]) / (bl["std"] or 1.0), 2)
        out[metric] = entry
    return out


# ---------------------------------------------------------------------------
# plan_adherence — lightweight single day
# ---------------------------------------------------------------------------

def plan_adherence(gs: GridStatsBundle, day: str) -> dict:
    """Per-metric de-biased plan adherence over a single calendar day.

    For each metric (load/solar/wind): mean |σ| over the day, the worst hour and
    its signed σ. A short verdict ("on plan" / "off plan: …") summarises the day.
    σ is the de-biased forecast surprise z-score.
    """
    day_ts = pd.Timestamp(day)
    err = _out_of_range(gs, day_ts.normalize())
    if err is not None:
        return err

    surprise = surprise_series(gs)
    mask = surprise.index.normalize() == day_ts.normalize()
    day_surprise = surprise[mask]
    if day_surprise.empty:
        return {
            "error": (
                f"{day_ts.date().isoformat()} has no data in dataset window "
                f"({gs.first_ts} … {gs.last_ts})."
            )
        }

    metrics_out: dict = {}
    worst_overall = 0.0
    worst_metric = None
    for metric in day_surprise.columns:
        s = day_surprise[metric].dropna()
        if s.empty:
            continue
        abs_s = s.abs()
        worst_idx = abs_s.idxmax()
        mean_abs = round(_f(abs_s.mean()), 2)
        worst_val = round(_f(s.loc[worst_idx]), 2)
        metrics_out[metric] = {
            "mean_abs_sigma": mean_abs,
            "worst_hour": pd.Timestamp(worst_idx).isoformat(),
            "worst_sigma": worst_val,
        }
        if abs(worst_val) > abs(worst_overall):
            worst_overall = worst_val
            worst_metric = metric

    # verdict: "off plan" if any metric's worst hour exceeds 2σ de-biased
    off = worst_metric is not None and abs(worst_overall) >= 2.0
    if off:
        verdict = (
            f"off plan: {worst_metric} hit {worst_overall:+.1f}σ (de-biased) on "
            f"{day_ts.date().isoformat()}"
        )
    else:
        verdict = f"on plan ({day_ts.date().isoformat()}): all metrics within 2σ de-biased"

    lines = [f"[{day_ts.date().isoformat()}] plan adherence (de-biased)"]
    for metric, d in metrics_out.items():
        lines.append(
            f"  {metric}: mean |σ|={d['mean_abs_sigma']}, "
            f"worst {d['worst_sigma']:+.1f}σ @ {d['worst_hour'][11:16]}"
        )
    lines.append(verdict)

    return {
        "day": day_ts.date().isoformat(),
        "metrics": metrics_out,
        "worst_metric": worst_metric,
        "worst_sigma": round(_f(worst_overall), 2),
        "off_plan": bool(off),
        "verdict": verdict,
        "summary_text": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# loading_context — lightweight single hour
# ---------------------------------------------------------------------------

def loading_context(gs: GridStatsBundle, timestamp: str, top: int = 5) -> dict:
    """Top branches by loading at a single hour, each with its normal band.

    For each branch: actual loading_percent and the p90/p95/p99 band for this
    hour-of-day × workday stratum, plus an approximate pct_rank within that band.
    """
    ts = pd.Timestamp(timestamp)
    err = _out_of_range(gs, ts)
    if err is not None:
        return err

    hour = ts.hour
    is_workday = int(ts.weekday() < 5)
    key = (hour, is_workday)

    row = _nearest_row(gs.branch_loadings, ts)
    loadings: dict[str, float] = {}
    for name, val in row.items():
        if val is None or (isinstance(val, float) and math.isnan(val)):
            continue
        loadings[str(name)] = round(float(val), 1)

    have_band = key in gs.branch_pct90.index
    p90_row = gs.branch_pct90.loc[key] if have_band else None
    p95_row = gs.branch_pct95.loc[key] if have_band else None
    p99_row = gs.branch_pct99.loc[key] if have_band else None

    branches: list[dict] = []
    for name, actual in sorted(loadings.items(), key=lambda x: -x[1])[:top]:
        entry: dict = {"name": name, "loading_pct": actual}
        if have_band and name in p90_row.index:
            p90 = p90_row[name]
            p95 = p95_row[name]
            p99 = p99_row[name]
            entry["p90"] = None if math.isnan(p90) else round(float(p90), 1)
            entry["p95"] = None if math.isnan(p95) else round(float(p95), 1)
            entry["p99"] = None if math.isnan(p99) else round(float(p99), 1)
            entry["pct_rank"] = _pct_rank(actual, p90, p95, p99)
        branches.append(entry)

    lines = [f"[{ts.isoformat()}] top {len(branches)} branch loadings vs normal band"]
    for b in branches:
        band = ""
        if "p90" in b:
            band = f" (p90/95/99={b['p90']}/{b['p95']}/{b['p99']}, ~{b['pct_rank']}th)"
        lines.append(f"  {b['name']}: {b['loading_pct']}%{band}")

    return {
        "timestamp": ts.isoformat(),
        "branches": branches,
        "summary_text": "\n".join(lines),
    }


def _pct_rank(actual: float, p90, p95, p99) -> int:
    """Coarse percentile bucket of ``actual`` within a p90/p95/p99 band."""
    if not math.isnan(p99) and actual >= p99:
        return 99
    if not math.isnan(p95) and actual >= p95:
        return 95
    if not math.isnan(p90) and actual >= p90:
        return 90
    return 0


# ---------------------------------------------------------------------------
# deep_dive — verbose & expensive single hour
# ---------------------------------------------------------------------------

def deep_dive(gs: GridStatsBundle, timestamp: str) -> dict:
    """Exhaustive single-hour breakdown. VERBOSE.

    Everything: all system metrics raw + z, full per-metric plan deviation
    (forecast/actual/delta/σ), ALL stressed branches with thresholds + pct_rank,
    momentum at 1h and 24h, and the day's plan-adherence context.
    """
    ts = pd.Timestamp(timestamp)
    err = _out_of_range(gs, ts)
    if err is not None:
        return err

    m = _nearest_row(gs.metrics, ts)
    resid = _nearest_row(gs.residuals, ts)

    metrics_z: dict = {}
    for col in gs.residuals.columns:
        std = gs.residual_std.get(col, 1.0) or 1.0
        metrics_z[col] = {
            "residual": round(_f(resid[col]), 2),
            "z": round(_f(resid[col]) / std, 2),
        }

    system = {
        "total_load_mw":        round(_f(m["total_load_mw"]), 1),
        "total_gen_mw":         round(_f(m["total_gen_mw"]), 1),
        "max_line_loading_pct": round(_f(m["max_line_loading_pct"]), 1),
        "slack_mw":             round(_f(m["slack_mw"]), 1),
        "n_overloaded_lines":   int(m["n_overloaded_lines"]) if "n_overloaded_lines" in m.index else 0,
        "converged":            bool(m["converged"]) if "converged" in m.index else True,
        "z": metrics_z,
    }

    fc_deltas = _forecast_deltas(gs, ts)

    # momentum 1h & 24h
    momentum: dict = {}
    for lag_h, label in [(1, "1h"), (24, "24h")]:
        prev_ts = ts - timedelta(hours=lag_h)
        if prev_ts in gs.metrics.index:
            pm = gs.metrics.loc[prev_ts]
            momentum[f"load_delta_{label}_mw"] = round(
                _f(m["total_load_mw"]) - _f(pm["total_load_mw"]), 1
            )
            momentum[f"loading_delta_{label}_pct"] = round(
                _f(m["max_line_loading_pct"]) - _f(pm["max_line_loading_pct"]), 1
            )

    all_branches = _stressed_branches(gs, ts, limit=None)

    day_ctx = plan_adherence(gs, ts.normalize().isoformat())

    lines = [f"[{ts.isoformat()}] DEEP DIVE"]
    lines.append(
        f"Load {system['total_load_mw']} MW (z={metrics_z.get('load', {}).get('z', 0):+.1f}), "
        f"max line loading {system['max_line_loading_pct']}% "
        f"(z={metrics_z.get('max_loading', {}).get('z', 0):+.1f}), "
        f"slack {system['slack_mw']:+.0f} MW (z={metrics_z.get('slack', {}).get('z', 0):+.1f})"
    )
    if fc_deltas:
        parts = []
        for metric, d in fc_deltas.items():
            sz = d.get("surprise_z")
            sz_txt = f", {sz:+.1f}σ" if sz is not None else ""
            parts.append(f"{metric} {d['delta_mw']:+.0f} MW ({d['delta_pct']:+.1f}%{sz_txt})")
        lines.append("Plan deviation (de-biased): " + ", ".join(parts))
    if momentum:
        lines.append(
            f"Trend: load {momentum.get('load_delta_1h_mw', 0):+.0f}/"
            f"{momentum.get('load_delta_24h_mw', 0):+.0f} MW (1h/24h), "
            f"max loading {momentum.get('loading_delta_1h_pct', 0):+.1f}/"
            f"{momentum.get('loading_delta_24h_pct', 0):+.1f}% (1h/24h)"
        )
    if all_branches:
        names = ", ".join(b["name"] for b in all_branches)
        lines.append(f"Stressed branches ({len(all_branches)}, ≥90th pct): {names}")
    if "verdict" in day_ctx:
        lines.append(f"Day context: {day_ctx['verdict']}")

    return {
        "timestamp": ts.isoformat(),
        "system": system,
        "forecast_deltas": fc_deltas,
        "momentum": momentum,
        "stressed_branches": all_branches,
        "day_context": day_ctx,
        "summary_text": "\n".join(lines),
    }
