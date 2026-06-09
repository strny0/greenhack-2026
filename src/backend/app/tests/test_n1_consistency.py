"""N-1 consistency & completeness (Spec S6).

The bug: run_n1 truncated the *analyzed* contingency set in raw line-table order,
so a low `limit` could MISS the worst/islanding contingency and report the grid
secure. The fix decouples "analyzed" (always all in-service lines) from
"returned" (`limit` slices the ranked list), and caches the full sweep per hour.
"""
from __future__ import annotations

from app import engine
from app.data_loader import store

# A known islanding hour: tripping branch_019_020_1 islands part of the grid, so
# the post-trip load flow does not converge.
TS = "2024-01-21T20:00:00"
ISLANDING = "branch_019_020_1"


def _key(r):
    return (r.contingency_name, r.converged, r.max_loading_pct)


def _in_service_line_count(ts: str) -> int:
    net = store.read_net(store.nearest_timestamp(ts))
    return int(net.line["in_service"].sum())


def test_islanding_never_missed():
    """The islanding contingency must surface at every limit — including the
    limit=20 that was broken before the fix."""
    for limit in (20, 40, 60, None):
        results = engine.run_n1(TS, limit=limit)
        hit = next((r for r in results if r.contingency_name == ISLANDING), None)
        assert hit is not None, f"{ISLANDING} missing at limit={limit}"
        assert hit.converged is False, f"{ISLANDING} should not converge at limit={limit}"


def test_limit_only_trims_tail():
    """The returned head must be stable: the first K of the full sweep equals the
    K returned by run_n1(limit=K)."""
    full = engine.run_n1(TS, limit=None)
    k = 10
    head = engine.run_n1(TS, limit=k)
    assert len(head) == k
    assert [_key(r) for r in full[:k]] == [_key(r) for r in head]


def test_determinism_and_cache():
    """Two calls for the same hour are identical, and the second is served from
    the cache (same list object)."""
    a = engine.run_n1(TS)
    b = engine.run_n1(TS)
    assert [_key(r) for r in a] == [_key(r) for r in b]
    # full sweep (limit=None) returns the cached list object itself
    assert engine.run_n1(TS, limit=None) is engine.run_n1(TS, limit=None)


def test_completeness_equals_in_service_count():
    """The full sweep analyzes (and returns) exactly the in-service lines."""
    full = engine.run_n1(TS, limit=None)
    assert len(full) == _in_service_line_count(TS)
