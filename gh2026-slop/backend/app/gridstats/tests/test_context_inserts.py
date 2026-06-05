"""Demonstrate the context inserts an LLM agent would receive from each tool.

These tests load the tiny committed fixture bundle (``fixtures/mini_target``, a
~2-week trim of the full year covering the wind-surprise day 2024-09-13 and the
peak-loading day 2024-09-08) and assert the shape + key narrative content of the
JSON-able insert each insight function returns. One golden snapshot pins the exact
``explain_hour`` ``summary_text`` so we can see precisely what gets injected into
the chatbot.

Run from the ``backend`` dir::

    python -m pytest app/gridstats/tests
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from app.gridstats import GridStats, tools

# Absolute path to the committed fixture bundle.
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "mini_target"

# An in-window hour: the wind-surprise day, evening peak.
TS = "2024-09-13T18:00:00"
# Window the fixture covers (inclusive).
WIN_START = "2024-09-08"
WIN_END = "2024-09-22"

VALID_DRIVERS = {"load", "solar", "wind", "loading"}

# Golden snapshot of the exact summary_text injected for explain_hour(TS).
# Captured from the real fixture; deterministic given the precomputed bundle.
GOLDEN_EXPLAIN_SUMMARY = (
    "[2024-09-13T18:00:00]\n"
    "Load 11938.3 MW (z=+0.3), max line loading 51.2% (z=+0.2), slack +115 MW (z=+0.2)\n"
    "Plan deviation (de-biased): solar -50 MW (-19.2%, +0.3σ), "
    "wind -190 MW (-41.0%, -1.8σ), load -456 MW (-3.7%, +2.3σ)\n"
    "Trend (1h): load +636 MW, max loading -0.5%\n"
    "Stressed branches (≥90th pct): "
    "branch_017_113_1, branch_002_012_1, branch_003_005_1"
)


@pytest.fixture(scope="module")
def gs() -> GridStats:
    """Load the fixture bundle once for the whole module."""
    assert FIXTURE_DIR.exists(), f"fixture bundle missing at {FIXTURE_DIR}"
    return GridStats.load(FIXTURE_DIR)


# ---------------------------------------------------------------------------
# explain_hour — compact single-hour insert
# ---------------------------------------------------------------------------

def test_explain_hour_insert_shape(gs: GridStats) -> None:
    out = gs.explain_hour(TS)

    # The insert carries system metrics, forecast deltas, and a summary line.
    assert "system" in out
    assert "forecast_deltas" in out
    assert "summary_text" in out

    # At least one metric carries a de-biased surprise z-score.
    deltas = out["forecast_deltas"]
    assert deltas, "expected forecast deltas for an in-window hour"
    assert any("surprise_z" in d for d in deltas.values())

    # The de-biased plan-deviation line is what gets narrated to the operator.
    assert "Plan deviation" in out["summary_text"]


def test_explain_hour_slack_not_a_driver(gs: GridStats) -> None:
    out = gs.explain_hour(TS)
    system = out["system"]

    # slack is shown but must not dominate: its STL z stays small, and slack is
    # never a forecast-deviation driver (it has no forecast_deltas entry at all).
    assert abs(system["z_slack"]) < 1.0
    assert "slack" not in out["forecast_deltas"]


def test_explain_hour_golden_summary(gs: GridStats) -> None:
    out = gs.explain_hour(TS)
    # Exact insert the chatbot would receive — pinned so changes are visible.
    assert out["summary_text"] == GOLDEN_EXPLAIN_SUMMARY


# ---------------------------------------------------------------------------
# interesting_days — the only range tool
# ---------------------------------------------------------------------------

def test_interesting_days_range_insert(gs: GridStats) -> None:
    df = gs.interesting_days(WIN_START, WIN_END, n=5)

    # At most n rows.
    assert len(df) <= 5

    # Every flagged day has one clear, valid driver.
    assert set(df["driver"]).issubset(VALID_DRIVERS)

    # Every date falls within the requested window.
    lo = pd.Timestamp(WIN_START).normalize()
    hi = pd.Timestamp(WIN_END).normalize()
    assert (df.index >= lo).all()
    assert (df.index <= hi).all()


# ---------------------------------------------------------------------------
# plan_adherence — single-day insert
# ---------------------------------------------------------------------------

def test_plan_adherence_insert(gs: GridStats) -> None:
    out = gs.plan_adherence("2024-09-13")

    # Per-metric de-biased sigma for each of load/solar/wind.
    metrics = out["metrics"]
    for metric in ("load", "solar", "wind"):
        assert metric in metrics
        assert "mean_abs_sigma" in metrics[metric]
        assert "worst_sigma" in metrics[metric]

    # A human-readable verdict / summary string.
    assert isinstance(out["verdict"], str) and out["verdict"]
    assert isinstance(out["summary_text"], str) and out["summary_text"]


# ---------------------------------------------------------------------------
# loading_context — branches carry their normal band
# ---------------------------------------------------------------------------

def test_loading_context_carries_bands(gs: GridStats) -> None:
    out = gs.loading_context(TS, top=5)
    branches = out["branches"]
    assert branches, "expected at least one branch"
    for b in branches:
        # Each branch carries its p90/p95/p99 normal band.
        assert "p90" in b
        assert "p95" in b
        assert "p99" in b


# ---------------------------------------------------------------------------
# deep_dive — exhaustive insert
# ---------------------------------------------------------------------------

def test_deep_dive_is_exhaustive(gs: GridStats) -> None:
    eh = gs.explain_hour(TS)
    dd = gs.deep_dive(TS)

    # deep_dive carries ALL stressed branches — strictly more than explain_hour's
    # top-3 — so the operator gets the full picture only when they ask for it.
    assert len(dd["stressed_branches"]) > len(eh["top_branches"])
    assert len(eh["top_branches"]) <= 3

    # Momentum at BOTH 1h and 24h.
    assert "load_delta_1h_mw" in dd["momentum"]
    assert "load_delta_24h_mw" in dd["momentum"]


def test_deep_dive_docstring_warns(gs: GridStats) -> None:
    doc = (tools.deep_dive.__doc__ or "").lower()
    # The LLM-facing description must warn this tier is heavyweight.
    assert "expensive" in doc or "only" in doc


# ---------------------------------------------------------------------------
# out-of-range guards
# ---------------------------------------------------------------------------

def test_explain_hour_out_of_range(gs: GridStats) -> None:
    out = gs.explain_hour("2030-01-01T00:00:00")
    assert "error" in out


def test_plan_adherence_out_of_range(gs: GridStats) -> None:
    # 2024-01-01 is inside the real dataset bounds but outside the trimmed
    # fixture window, so it has no servable data -> error insert.
    out = gs.plan_adherence("2024-01-01")
    assert "error" in out
