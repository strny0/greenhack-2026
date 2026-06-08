"""pandapower grid engine: load flow, canonical extraction, N-1, what-if.

Everything physical happens here. The rest of the app only sees the canonical
model (Node/Line/StateFrame). Load flow is `pp.runpp`; N-1 trips one element at a
time and re-solves; what-if applies operator actions and re-solves.
"""
from __future__ import annotations

import warnings
from collections import OrderedDict

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandapower as pp  # noqa: E402

from . import config  # noqa: E402
from .data_loader import store  # noqa: E402
from .forecast import forecast_store  # noqa: E402
from .model import (  # noqa: E402
    Alert,
    ContingencyResult,
    FrameSummary,
    Line,
    Node,
    ScenarioSpec,
    State,
    StateFrame,
    WhatIfRequest,
    WhatIfResponse,
)

# --- classification / state helpers -----------------------------------------


def _node_type(has_gen: bool, has_load: bool, is_slack: bool) -> str:
    if is_slack:
        return "slack"
    if has_gen:
        return "generation"
    if has_load:
        return "load"
    return "substation"


def _node_state(vm_pu: float | None, lo: float, hi: float) -> State:
    """Judge bus voltage against its own rated band [lo, hi] with a warn margin."""
    if vm_pu is None or np.isnan(vm_pu):
        return "offline"
    m = config.VOLTAGE_WARN_MARGIN
    if vm_pu >= hi or vm_pu <= lo:
        return "alert"
    if vm_pu >= hi - m or vm_pu <= lo + m:
        return "warn"
    return "ok"


def _line_state(loading: float | None, in_service: bool) -> State:
    if not in_service:
        return "offline"
    if loading is None or np.isnan(loading):
        return "offline"
    if loading >= config.LINE_LOADING_ALERT:
        return "alert"
    if loading >= config.LINE_LOADING_WARN:
        return "warn"
    return "ok"


# --- canonical extraction ----------------------------------------------------


def _solve(net) -> bool:
    """Run AC load flow; return convergence flag (never raises).

    Tries a flat start, then a DC-initialised start with more iterations. A
    persistent failure is a *meaningful* result here: for an N-1 trip of a radial
    feeder or an overloaded scenario it signals islanding / voltage collapse.
    """
    for init in ("flat", "dc"):
        try:
            pp.runpp(net, calculate_voltage_angles=True, init=init, max_iteration=50)
            if bool(net.converged):
                return True
        except Exception:
            continue
    return False


def extract_frame(net, timestamp: str, converged: bool) -> StateFrame:
    """Build the canonical StateFrame from an (already solved) pandapower net."""
    bus = net.bus
    name_by_idx = bus["name"].to_dict()
    bus_lonlat = store.bus_lonlat
    bus_labels = store.bus_labels
    branch_labels = store.branch_labels

    # aggregate generation / load per bus index
    gen_p = (
        net.res_gen["p_mw"]
        if converged and len(net.res_gen)
        else net.gen.get("p_mw")
    )
    gen_by_bus: dict[int, float] = {}
    gen_count: dict[int, int] = {}
    for idx, row in net.gen.iterrows():
        if not row["in_service"]:
            continue
        b = int(row["bus"])
        p = float(gen_p.get(idx, 0.0)) if gen_p is not None else float(row["p_mw"])
        gen_by_bus[b] = gen_by_bus.get(b, 0.0) + (p if not np.isnan(p) else 0.0)
        gen_count[b] = gen_count.get(b, 0) + 1

    load_by_bus: dict[int, float] = {}
    load_count: dict[int, int] = {}
    for idx, row in net.load.iterrows():
        if not row["in_service"]:
            continue
        b = int(row["bus"])
        p = float(row["p_mw"])
        load_by_bus[b] = load_by_bus.get(b, 0.0) + (p if not np.isnan(p) else 0.0)
        load_count[b] = load_count.get(b, 0) + 1

    slack_buses = set()
    if len(net.ext_grid):
        slack_buses |= {int(b) for b in net.ext_grid["bus"].tolist()}
    slack_buses |= {int(r["bus"]) for _, r in net.gen.iterrows() if r.get("slack")}

    nodes: list[Node] = []
    for idx, row in bus.iterrows():
        vm = (
            float(net.res_bus.at[idx, "vm_pu"])
            if converged and idx in net.res_bus.index
            else None
        )
        va = (
            float(net.res_bus.at[idx, "va_degree"])
            if converged and idx in net.res_bus.index
            else None
        )
        vn = float(row["vn_kv"])
        prod = gen_by_bus.get(idx, 0.0)
        cons = load_by_bus.get(idx, 0.0)
        is_slack = idx in slack_buses
        lo, hi = float(row["min_vm_pu"]), float(row["max_vm_pu"])
        bus_name = str(row["name"])
        lon, lat = bus_lonlat.get(bus_name, (0.0, 0.0))
        nodes.append(
            Node(
                id=bus_name,
                name=bus_name,
                label=bus_labels.get(bus_name, bus_name),
                type=_node_type(idx in gen_by_bus, idx in load_by_bus, is_slack),
                zone=str(row.get("zone", "")),
                lat=round(lat, 5),
                lon=round(lon, 5),
                v_nominal_kv=vn,
                is_slack=is_slack,
                min_vm_pu=lo,
                max_vm_pu=hi,
                gen_types=store.bus_gen_types.get(bus_name, []) if idx in gen_by_bus else [],
                vm_pu=round(vm, 4) if vm is not None else None,
                vm_kv=round(vm * vn, 2) if vm is not None else None,
                va_degree=round(va, 2) if va is not None else None,
                production_mw=round(prod, 2),
                consumption_mw=round(cons, 2),
                net_mw=round(prod - cons, 2),
                n_gens=gen_count.get(idx, 0),
                n_loads=load_count.get(idx, 0),
                state=_node_state(vm, lo, hi),
            )
        )

    lines: list[Line] = []
    for idx, row in net.line.iterrows():
        loading = (
            float(net.res_line.at[idx, "loading_percent"])
            if converged and idx in net.res_line.index
            else None
        )
        pf = (
            float(net.res_line.at[idx, "p_from_mw"])
            if converged and idx in net.res_line.index
            else None
        )
        pt = (
            float(net.res_line.at[idx, "p_to_mw"])
            if converged and idx in net.res_line.index
            else None
        )
        ika = (
            float(net.res_line.at[idx, "i_ka"])
            if converged and idx in net.res_line.index
            else None
        )
        in_svc = bool(row["in_service"])
        line_name = str(row["name"])
        lines.append(
            Line(
                id=line_name,
                name=line_name,
                label=branch_labels.get(line_name, line_name),
                from_node=name_by_idx[int(row["from_bus"])],
                to_node=name_by_idx[int(row["to_bus"])],
                kind="line",
                max_i_ka=float(row.get("max_i_ka", 0.0) or 0.0),
                loading_pct=round(loading, 1) if loading is not None and not np.isnan(loading) else None,
                p_from_mw=round(pf, 2) if pf is not None and not np.isnan(pf) else None,
                p_to_mw=round(pt, 2) if pt is not None and not np.isnan(pt) else None,
                i_ka=round(ika, 4) if ika is not None and not np.isnan(ika) else None,
                in_service=in_svc,
                state=_line_state(loading, in_svc),
            )
        )

    # transformers as lines (kind=trafo)
    for idx, row in net.trafo.iterrows():
        loading = (
            float(net.res_trafo.at[idx, "loading_percent"])
            if converged and idx in net.res_trafo.index
            else None
        )
        pf = (
            float(net.res_trafo.at[idx, "p_hv_mw"])
            if converged and idx in net.res_trafo.index
            else None
        )
        in_svc = bool(row["in_service"])
        nm = str(row["name"]) if row.get("name") is not None else f"trafo_{idx}"
        lines.append(
            Line(
                id=nm,
                name=nm,
                label=branch_labels.get(nm, nm),
                from_node=name_by_idx[int(row["hv_bus"])],
                to_node=name_by_idx[int(row["lv_bus"])],
                kind="trafo",
                max_i_ka=0.0,
                loading_pct=round(loading, 1) if loading is not None and not np.isnan(loading) else None,
                p_from_mw=round(pf, 2) if pf is not None and not np.isnan(pf) else None,
                p_to_mw=None,
                i_ka=None,
                in_service=in_svc,
                state=_line_state(loading, in_svc),
            )
        )

    # summary
    total_gen = sum(gen_by_bus.values())
    if converged and len(net.res_ext_grid):
        slack_mw = float(net.res_ext_grid["p_mw"].sum())
        total_gen += max(slack_mw, 0.0)
    else:
        slack_mw = 0.0
    total_load = sum(load_by_bus.values())
    loadings = [l.loading_pct for l in lines if l.loading_pct is not None]
    max_loading = max(loadings) if loadings else 0.0
    n_alerts = sum(1 for n in nodes if n.state == "alert") + sum(
        1 for l in lines if l.state == "alert"
    )
    n_warn = sum(1 for n in nodes if n.state == "warn") + sum(
        1 for l in lines if l.state == "warn"
    )

    summary = FrameSummary(
        timestamp=timestamp,
        converged=converged,
        total_generation_mw=round(total_gen, 1),
        total_load_mw=round(total_load, 1),
        slack_mw=round(slack_mw, 1),
        losses_mw=round(total_gen - total_load, 1),
        max_loading_pct=round(max_loading, 1),
        n_alerts=n_alerts,
        n_warnings=n_warn,
    )
    return StateFrame(timestamp=timestamp, summary=summary, nodes=nodes, lines=lines)


# --- frame cache -------------------------------------------------------------

_frame_cache: "OrderedDict[str, StateFrame]" = OrderedDict()


def base_frame(timestamp: str) -> StateFrame:
    """Solved canonical frame for a snapshot timestamp (LRU cached)."""
    ts = store.nearest_timestamp(timestamp)
    if ts in _frame_cache:
        _frame_cache.move_to_end(ts)
        return _frame_cache[ts]
    net = store.read_net(ts)
    converged = _solve(net)
    frame = extract_frame(net, ts, converged)
    _frame_cache[ts] = frame
    if len(_frame_cache) > config.FRAME_CACHE_SIZE:
        _frame_cache.popitem(last=False)
    return frame


def preload(start: int, count: int) -> int:
    """Warm the frame cache for a window; returns number of frames loaded."""
    tss = store.timestamps[start : start + count]
    for ts in tss:
        base_frame(ts)
    return len(tss)


def _series_for(
    tss: list[str], element_id: str, kind: str, metric: str
) -> tuple[list[str], list[float | None]]:
    """Pull one metric for `element_id` across the given solved frames."""
    t_out: list[str] = []
    v_out: list[float | None] = []
    for ts in tss:
        frame = base_frame(ts)
        val = None
        if kind == "line":
            el = next((l for l in frame.lines if l.id == element_id), None)
            if el is not None:
                val = {"loading": el.loading_pct, "p_from": el.p_from_mw}.get(metric)
        else:
            el = next((n for n in frame.nodes if n.id == element_id), None)
            if el is not None:
                val = {
                    "vm_pu": el.vm_pu,
                    "production": el.production_mw,
                    "consumption": el.consumption_mw,
                    "net": el.net_mw,
                }.get(metric)
        t_out.append(ts)
        v_out.append(val)
    return t_out, v_out


def element_timeseries(
    element_id: str, kind: str, metric: str, start_ts: str, count: int
) -> dict:
    """Forward metric history for one element (used by /api/timeseries).

    kind="line" metric in {loading, p_from}; kind="node" metric in
    {vm_pu, production, consumption, net}.
    """
    start_idx = store.timestamps.index(store.nearest_timestamp(start_ts))
    tss = store.timestamps[start_idx : start_idx + count]
    t_out, v_out = _series_for(tss, element_id, kind, metric)
    return {"element_id": element_id, "kind": kind, "metric": metric, "t": t_out, "v": v_out}


def element_window(
    element_id: str,
    kind: str,
    metric: str,
    center_ts: str,
    hours_back: int,
    hours_fwd: int,
) -> dict:
    """Bidirectional history around `center_ts`: `hours_back` into the past and
    `hours_fwd` into the future (inclusive of the centre hour).

    Reports `truncated_past` / `truncated_future` when the window hits a dataset
    edge so callers can be honest about how much history actually exists.
    """
    ci = store.timestamps.index(store.nearest_timestamp(center_ts))
    n = len(store.timestamps)
    lo = ci - max(0, hours_back)
    hi = ci + max(0, hours_fwd)
    tss = store.timestamps[max(0, lo) : min(n, hi + 1)]
    t_out, v_out = _series_for(tss, element_id, kind, metric)
    return {
        "element_id": element_id,
        "kind": kind,
        "metric": metric,
        "center": store.timestamps[ci],
        "t": t_out,
        "v": v_out,
        "truncated_past": lo < 0,
        "truncated_future": hi > n - 1,
    }


def neighbors(timestamp: str, bus_id: str, hops: int = 1) -> dict:
    """Local topology around a bus for network traversal.

    Returns the branches incident to `bus_id` and every bus reachable within
    `hops` (1-3), each tagged with its hop distance and type. Built from the
    canonical frame, so each branch also carries its live loading.
    """
    f = base_frame(timestamp)
    nodes_by_id = {n.id: n for n in f.nodes}
    if bus_id not in nodes_by_id:
        return {"error": f"No bus '{bus_id}'. Check the id with grid_summary / a detail tool."}

    hops = max(1, min(hops, 3))
    adj: dict[str, list[tuple]] = {}
    for l in f.lines:
        adj.setdefault(l.from_node, []).append((l, l.to_node))
        adj.setdefault(l.to_node, []).append((l, l.from_node))

    dist = {bus_id: 0}
    edges: dict[str, dict] = {}
    frontier = [bus_id]
    depth = 0
    while frontier and depth < hops:
        depth += 1
        nxt: list[str] = []
        for b in frontier:
            for l, other in adj.get(b, []):
                edges[l.id] = {
                    "branch": l.id,
                    "kind": l.kind,
                    "from": l.from_node,
                    "to": l.to_node,
                    "loading_pct": l.loading_pct,
                    "in_service": l.in_service,
                }
                if other not in dist:
                    dist[other] = depth
                    nxt.append(other)
        frontier = nxt

    neigh = [
        {"bus": bid, "hops": h, "type": nodes_by_id[bid].type}
        for bid, h in sorted(dist.items(), key=lambda kv: (kv[1], kv[0]))
        if bid != bus_id
    ]
    degree = sum(1 for e in edges.values() if e["from"] == bus_id or e["to"] == bus_id)
    return {
        "bus": bus_id,
        "hops": hops,
        "degree": degree,
        "neighbors": neigh,
        "branches": list(edges.values()),
    }


# --- alerts ------------------------------------------------------------------


def build_alerts(frame: StateFrame) -> list[Alert]:
    alerts: list[Alert] = []
    for l in frame.lines:
        if l.loading_pct is None:
            continue
        if l.loading_pct >= config.LINE_LOADING_ALERT:
            alerts.append(
                Alert(
                    id=f"line:{l.id}",
                    severity="alert",
                    category="line_loading",
                    element_kind="line",
                    element_id=l.id,
                    message=f"{l.name} loaded at {l.loading_pct:.0f}% (≥{config.LINE_LOADING_ALERT:.0f}%)",
                    value=l.loading_pct,
                )
            )
        elif l.loading_pct >= config.LINE_LOADING_WARN:
            alerts.append(
                Alert(
                    id=f"line:{l.id}",
                    severity="warn",
                    category="line_loading",
                    element_kind="line",
                    element_id=l.id,
                    message=f"{l.name} loaded at {l.loading_pct:.0f}%",
                    value=l.loading_pct,
                )
            )
    for n in frame.nodes:
        if n.vm_pu is None:
            continue
        if n.state == "alert":
            alerts.append(
                Alert(
                    id=f"node:{n.id}",
                    severity="alert",
                    category="voltage",
                    element_kind="node",
                    element_id=n.id,
                    message=f"{n.name} voltage {n.vm_pu:.3f} p.u. out of safe band",
                    value=n.vm_pu,
                )
            )
        elif n.state == "warn":
            alerts.append(
                Alert(
                    id=f"node:{n.id}",
                    severity="warn",
                    category="voltage",
                    element_kind="node",
                    element_id=n.id,
                    message=f"{n.name} voltage {n.vm_pu:.3f} p.u. near limit",
                    value=n.vm_pu,
                )
            )
    severity_rank = {"alert": 0, "warn": 1}
    alerts.sort(key=lambda a: (severity_rank[a.severity], -(a.value or 0)))
    return alerts


# --- N-1 security analysis ---------------------------------------------------


def run_n1(timestamp: str, limit: int | None = None) -> list[ContingencyResult]:
    """Trip each in-service line one at a time, re-solve, rank by stress."""
    ts = store.nearest_timestamp(timestamp)
    net = store.read_net(ts)
    if not _solve(net):
        return []
    name_by_idx = net.bus["name"].to_dict()  # noqa: F841 (kept for parity)
    cap = limit or config.N1_MAX_CONTINGENCIES
    line_ids = [
        idx for idx, r in net.line.iterrows() if bool(r["in_service"])
    ][:cap]

    results: list[ContingencyResult] = []
    for idx in line_ids:
        cname = str(net.line.at[idx, "name"])
        net.line.at[idx, "in_service"] = False
        ok = _solve(net)
        if ok and len(net.res_line):
            res = net.res_line["loading_percent"]
            overloaded = []
            for j, val in res.items():
                if j == idx or np.isnan(val):
                    continue
                if val >= config.N1_OVERLOAD_PCT:
                    overloaded.append(
                        {
                            "id": str(net.line.at[j, "name"]),
                            "name": str(net.line.at[j, "name"]),
                            "loading_pct": round(float(val), 1),
                        }
                    )
            max_loading = float(
                np.nanmax(res.drop(index=idx)) if len(res) > 1 else 0.0
            )
            overloaded.sort(key=lambda o: -o["loading_pct"])
            results.append(
                ContingencyResult(
                    contingency_id=cname,
                    contingency_name=cname,
                    converged=True,
                    max_loading_pct=round(max_loading, 1),
                    n_overloads=len(overloaded),
                    overloaded=overloaded[:10],
                )
            )
        else:
            results.append(
                ContingencyResult(
                    contingency_id=cname,
                    contingency_name=cname,
                    converged=False,
                    max_loading_pct=0.0,
                    n_overloads=0,
                    overloaded=[],
                )
            )
        net.line.at[idx, "in_service"] = True

    # rank: non-converged (islanding) first, then by worst resulting loading
    results.sort(key=lambda r: (r.converged, -r.max_loading_pct))
    return results


# --- forecast-vs-actual deviation triage ------------------------------------

_actuals_cache: "OrderedDict[str, dict]" = OrderedDict()


def attribution_actuals(timestamp: str) -> dict:
    """Per-generator actual solar/wind output and per-region actual load, read
    from the solved snapshot. Complements forecast.planned_at() for deviation.

    (base_frame aggregates generation per *bus* only, so we read res_gen here to
    recover per-generator values.) LRU-cached like the frame cache.
    """
    ts = store.nearest_timestamp(timestamp)
    if ts in _actuals_cache:
        _actuals_cache.move_to_end(ts)
        return _actuals_cache[ts]

    net = store.read_net(ts)
    converged = _solve(net)
    gen_p = net.res_gen["p_mw"] if converged and len(net.res_gen) else net.gen.get("p_mw")
    name_by_idx = net.bus["name"].to_dict()

    solar: dict[str, float] = {}
    wind: dict[str, float] = {}
    for idx, row in net.gen.iterrows():
        if not row["in_service"]:
            continue
        name = str(row["name"])
        p = float(gen_p.get(idx, 0.0)) if gen_p is not None else float(row["p_mw"])
        if np.isnan(p):
            p = 0.0
        if name.startswith("solar"):
            solar[name] = round(p, 2)
        elif name.startswith("wind"):
            wind[name] = round(p, 2)

    load_by_region: dict[str, float] = {}
    for _, row in net.load.iterrows():
        if not row["in_service"]:
            continue
        bus = name_by_idx.get(int(row["bus"]))
        region = store.bus_to_region.get(bus)
        if region is None:
            continue
        p = float(row["p_mw"])
        load_by_region[region] = load_by_region.get(region, 0.0) + (0.0 if np.isnan(p) else p)
    load_by_region = {r: round(v, 2) for r, v in load_by_region.items()}

    result = {"converged": converged, "solar": solar, "wind": wind, "load_by_region": load_by_region}
    _actuals_cache[ts] = result
    if len(_actuals_cache) > config.FRAME_CACHE_SIZE:
        _actuals_cache.popitem(last=False)
    return result


def _pct(delta: float, base: float) -> float | None:
    """delta as a percentage of a (planned) base; None when the base is ~0."""
    return round(delta / base * 100, 1) if abs(base) > 1e-6 else None


def assess_deviation(timestamp: str) -> dict:
    """Compare the DA plan to the actual snapshot at `timestamp` and gather the
    grid-security context needed to triage it. Pure data — the *verdict* (risk
    tier / notify) is left to the agent, but a deterministic `safety_net` floor
    is computed here so a real breach can never be silently suppressed.
    """
    ts = store.nearest_timestamp(timestamp)
    planned = forecast_store.planned_at(ts)
    actual = attribution_actuals(ts)

    # per-generator deviations (Δ = actual − plan; negative = under-producing)
    deviations: list[dict] = []
    for kind, plan_map, act_map in (
        ("solar", planned["solar"], actual["solar"]),
        ("wind", planned["wind"], actual["wind"]),
    ):
        for gen, plan_mw in plan_map.items():
            act_mw = act_map.get(gen, 0.0)
            delta = act_mw - plan_mw
            deviations.append(
                {
                    "kind": kind,
                    "gen": gen,
                    "bus": store.gen_to_bus.get(gen),
                    "planned_mw": round(plan_mw, 2),
                    "actual_mw": round(act_mw, 2),
                    "delta_mw": round(delta, 2),
                    "pct": _pct(delta, plan_mw),
                }
            )
    deviations.sort(key=lambda d: -abs(d["delta_mw"]))

    # system-level totals (include unmapped forecast series so totals stay honest)
    def _sys(kind: str, unmapped_mw: float) -> dict:
        plan_total = sum(planned[kind].values()) + unmapped_mw
        act_total = sum(actual[kind].values())
        delta = act_total - plan_total
        return {
            "planned_mw": round(plan_total, 1),
            "actual_mw": round(act_total, 1),
            "delta_mw": round(delta, 1),
            "pct": _pct(delta, plan_total),
        }

    system = {
        "solar": _sys("solar", planned["solar_unmapped_mw"]),
        "wind": _sys("wind", planned["wind_unmapped_mw"]),
    }

    # per-region load deviation. The DA load forecast in this dataset carries a
    # large *systematic* high baseline (~12-19% every hour), so a raw plan-vs-
    # actual % would scream every hour. We remove that common-mode bias by
    # scoring each region against the system-wide plan->actual ratio: a region
    # tracking the global offset reads ~0; only a genuinely anomalous region
    # (the actionable "where") stands out. Raw numbers are kept for transparency.
    total_plan_load = sum(planned["load_by_region"].values())
    total_act_load = sum(
        actual["load_by_region"].get(r, 0.0) for r in planned["load_by_region"]
    )
    load_ratio = (total_act_load / total_plan_load) if total_plan_load > 1e-6 else 1.0
    load_dev: list[dict] = []
    for region, plan_mw in planned["load_by_region"].items():
        act_mw = actual["load_by_region"].get(region, 0.0)
        delta = act_mw - plan_mw
        expected_mw = plan_mw * load_ratio  # what this region "should" be given the bias
        anomaly_mw = act_mw - expected_mw
        load_dev.append(
            {
                "region": region,
                "planned_mw": round(plan_mw, 1),
                "actual_mw": round(act_mw, 1),
                "delta_mw": round(delta, 1),
                "pct": _pct(delta, plan_mw),
                "anomaly_mw": round(anomaly_mw, 1),  # bias-corrected (the alarm signal)
                "anomaly_pct": _pct(anomaly_mw, expected_mw),
            }
        )
    load_dev.sort(key=lambda d: -abs(d["anomaly_mw"]))

    # grid impact, read off the same solved frame
    frame = base_frame(ts)
    s = frame.summary
    alerts = build_alerts(frame)
    breaches = [a for a in alerts if a.severity == "alert"]

    # significance gate (drives conditional N-1 + weather)
    # Significance is driven by RENEWABLE deviation only. The DA load forecast is
    # structurally divergent from the snapshots here (different magnitude AND
    # regional split), so it can't be a reliable alarm — and load-driven risk is
    # already captured by the realized grid state (alerts / loading / balancing
    # below). Renewable shortfall is the signal the forecast uniquely adds.
    significant = (
        abs(system["solar"]["delta_mw"]) >= config.DEV_SOLAR_MW
        or abs(system["wind"]["delta_mw"]) >= config.DEV_WIND_MW
    )
    grid_stressed = (
        (not s.converged) or s.n_alerts > 0 or s.max_loading_pct >= config.LINE_LOADING_WARN
    )

    # deterministic safety net — force a notification regardless of the agent
    slack_over = abs(s.slack_mw) >= config.DEV_SLACK_LOAD_FRACTION * max(s.total_load_mw, 1.0)
    force_reasons: list[str] = []
    if not s.converged:
        force_reasons.append("load flow did not converge")
    if breaches:
        force_reasons.append(f"{len(breaches)} active breach(es) (overload/voltage)")
    if slack_over:
        force_reasons.append(
            f"balancing power {s.slack_mw:.0f} MW exceeds "
            f"{config.DEV_SLACK_LOAD_FRACTION:.0%} of load"
        )

    # forward fragility — only when it's worth the cost
    n1 = {"ran": False, "worst": []}
    if significant or grid_stressed:
        results = run_n1(ts, limit=config.N1_DEV_LIMIT)
        n1 = {
            "ran": True,
            "worst": [
                {
                    "tripped": r.contingency_name,
                    "converged": r.converged,
                    "max_loading_pct": r.max_loading_pct,
                    "n_overloads": r.n_overloads,
                }
                for r in results[:5]
            ],
        }

    # does the agent need a cause check? (generation under plan => maybe weather)
    solar_shortfall_mw = round(-system["solar"]["delta_mw"], 1)  # positive = under plan
    wind_shortfall_mw = round(-system["wind"]["delta_mw"], 1)

    return {
        "timestamp": ts,
        "system": system,
        "worst_deviations": deviations,
        "load_by_region": load_dev,
        "grid": {
            "converged": s.converged,
            "total_generation_mw": s.total_generation_mw,
            "total_load_mw": s.total_load_mw,
            "balancing_mw": s.slack_mw,
            "max_line_loading_pct": s.max_loading_pct,
            "n_alerts": s.n_alerts,
            "n_warnings": s.n_warnings,
            "active_breaches": [
                {"element_id": a.element_id, "message": a.message} for a in breaches[:8]
            ],
        },
        "n1": n1,
        "significant": significant,
        "generation_shortfall": {"solar_mw": solar_shortfall_mw, "wind_mw": wind_shortfall_mw},
        "safety_net": {"force_notify": bool(force_reasons), "reasons": force_reasons},
        "data_quality": {
            "unmapped_series": planned["unmapped"],
            "units_warning": planned["units_warning"],
            "missing_forecast_for_hour": planned["missing_ts"],
            "load_forecast_actual_ratio": round(load_ratio, 3),
            "load_note": (
                "ADVISORY ONLY: the DA load forecast is structurally divergent from "
                "the snapshot in this dataset (systematic high baseline AND a "
                "different regional split), so per-region load deviation is NOT a "
                "reliable alarm and does not drive significance. Real load-driven "
                "risk shows up in the grid block (alerts / loading / balancing). "
                "'anomaly_mw' is bias-corrected; treat it as weak context, not a breach."
            ),
        },
    }


# --- what-if scenarios -------------------------------------------------------

LOAD_SURGE_SCALE = 1.5  # global load multiplier for the "load surge" preset


def _apply_scenario(net, disconnect_lines, trip_nodes, load_scale) -> None:
    """Mutate a pandapower net in place: take lines out of service, trip buses
    (drop their gens/loads), and/or scale all load. Shared by run_whatif and the
    whole-day simulation path so both behave identically."""
    name_to_line_idx = {str(r["name"]): idx for idx, r in net.line.iterrows()}
    for lid in disconnect_lines:
        if lid in name_to_line_idx:
            net.line.at[name_to_line_idx[lid], "in_service"] = False

    if trip_nodes:
        bus_idx_by_name = {str(r["name"]): idx for idx, r in net.bus.iterrows()}
        trip_bus_idx = {bus_idx_by_name[n] for n in trip_nodes if n in bus_idx_by_name}
        for idx, r in net.gen.iterrows():
            if int(r["bus"]) in trip_bus_idx:
                net.gen.at[idx, "in_service"] = False
        for idx, r in net.load.iterrows():
            if int(r["bus"]) in trip_bus_idx:
                net.load.at[idx, "in_service"] = False

    if load_scale != 1.0:
        net.load["p_mw"] = net.load["p_mw"] * load_scale
        net.load["q_mvar"] = net.load["q_mvar"] * load_scale


def scenario_frame(timestamp: str, spec: ScenarioSpec) -> StateFrame:
    """Solved canonical frame for a snapshot with a scenario applied (not cached)."""
    ts = store.nearest_timestamp(timestamp)
    net = store.read_net(ts)
    _apply_scenario(net, spec.disconnect_lines, spec.trip_nodes, spec.load_scale)
    converged = _solve(net)
    return extract_frame(net, ts, converged)


def resolve_preset(preset: str, timestamp: str) -> ScenarioSpec:
    """Turn a preset key into a concrete ScenarioSpec, picking the target element
    (the most-loaded line / largest generator) from the base frame at this hour."""
    ts = store.nearest_timestamp(timestamp)
    base = base_frame(ts)
    if preset == "trip_most_loaded_line":
        cand = [l for l in base.lines if l.in_service and l.loading_pct is not None]
        if not cand:
            return ScenarioSpec(preset=preset, feasible=False, reason="No in-service line to trip.")
        line = max(cand, key=lambda l: l.loading_pct)
        return ScenarioSpec(
            preset=preset,
            label=f"Tripped line {line.label or line.name} (was {round(line.loading_pct)}% loaded)",
            disconnect_lines=[line.id],
            resolved=[line.id],
        )
    if preset == "trip_largest_generator":
        cand = [n for n in base.nodes if n.production_mw > 0]
        if not cand:
            return ScenarioSpec(preset=preset, feasible=False, reason="No online generation to trip.")
        bus = max(cand, key=lambda n: n.production_mw)
        return ScenarioSpec(
            preset=preset,
            label=f"Tripped generation at {bus.label or bus.name} ({round(bus.production_mw)} MW offline)",
            trip_nodes=[bus.id],
            resolved=[bus.id],
        )
    if preset == "load_surge":
        return ScenarioSpec(
            preset=preset,
            label=f"Load surge +{round((LOAD_SURGE_SCALE - 1) * 100)}% across all buses",
            load_scale=LOAD_SURGE_SCALE,
        )
    return ScenarioSpec(preset=preset, feasible=False, reason=f"Unknown preset '{preset}'.")


def whatif_window(start: int, count: int, preset: str) -> tuple[ScenarioSpec, list[StateFrame]]:
    """Resolve a preset once at the window's first hour (fixed for the whole day),
    then solve a scenario frame for each of `count` hours. Returns (spec, frames)."""
    tss = store.timestamps[start : start + count]
    if not tss:
        return ScenarioSpec(preset=preset, feasible=False, reason="Empty window."), []
    spec = resolve_preset(preset, tss[0])
    if not spec.feasible:
        return spec, []
    frames = [scenario_frame(ts, spec) for ts in tss]
    return spec, frames


def run_whatif(req: WhatIfRequest) -> WhatIfResponse:
    ts = store.nearest_timestamp(req.timestamp)
    base = base_frame(ts)

    net = store.read_net(ts)
    _apply_scenario(net, req.disconnect_lines, req.trip_nodes, req.load_scale)

    converged = _solve(net)
    scenario = extract_frame(net, ts, converged)

    # per-line loading diff
    base_by_id = {l.id: l for l in base.lines}
    diffs = []
    for l in scenario.lines:
        b = base_by_id.get(l.id)
        before = b.loading_pct if b else None
        after = l.loading_pct
        if before is not None and after is not None:
            diffs.append(
                {
                    "id": l.id,
                    "name": l.name,
                    "before": before,
                    "after": after,
                    "delta": round(after - before, 1),
                }
            )
    diffs.sort(key=lambda d: -abs(d["delta"]))

    base_alert_ids = {a.element_id for a in build_alerts(base) if a.severity == "alert"}
    new_alerts = [
        a
        for a in build_alerts(scenario)
        if a.severity == "alert" and a.element_id not in base_alert_ids
    ]

    return WhatIfResponse(base=base, scenario=scenario, diffs=diffs, new_alerts=new_alerts)
