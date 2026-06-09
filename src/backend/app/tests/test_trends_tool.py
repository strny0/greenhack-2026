"""Tests for the long_term_trends gridstats tool (spec S3)."""
from __future__ import annotations

from app import agent
from app.gridstats import tools as gst
from app.gridstats.tools import _gs


def _a_branch_id() -> str:
    """A real branch id from the loaded bundle (don't hardcode)."""
    return str(_gs().bundle.branch_loadings.columns[0])


def _a_bundle_hour() -> str:
    return _gs().bundle.metrics.index[100].isoformat()


def test_month_load_returns_twelve_buckets():
    out = gst.long_term_trends("load", granularity="month")
    assert "error" not in out
    assert out["metric"] == "load"
    assert out["granularity"] == "month"
    assert out["unit"] == "MW"
    assert len(out["buckets"]) == 12
    assert out["overall"]["mean"] > 0
    for key in ("metric", "element_id", "granularity", "unit", "span", "buckets", "overall", "trend"):
        assert key in out
    assert out["trend"] in ("rising", "falling", "flat")


def test_line_loading_hour_of_day_returns_24_buckets_pct_unit():
    bid = _a_branch_id()
    out = gst.long_term_trends("line_loading", element_id=bid, granularity="hour_of_day")
    assert "error" not in out
    assert out["unit"] == "%"
    assert out["element_id"] == bid
    assert len(out["buckets"]) == 24


def test_unknown_metric_returns_error():
    out = gst.long_term_trends("nonsense_metric")
    assert "error" in out


def test_unknown_element_id_returns_error():
    out = gst.long_term_trends("line_loading", element_id="branch_does_not_exist")
    assert "error" in out


def test_current_pct_rank_is_int_0_100():
    out = gst.long_term_trends("load", granularity="month", current_ts=_a_bundle_hour())
    rank = out["overall"]["current_pct_rank"]
    assert isinstance(rank, int)
    assert 0 <= rank <= 100


def test_tool_registered():
    assert "long_term_trends" in agent.agent._function_toolset.tools
