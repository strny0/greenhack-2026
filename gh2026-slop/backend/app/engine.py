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
from .model import (  # noqa: E402
    Alert,
    ContingencyResult,
    FrameSummary,
    Line,
    Node,
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
    proj = store.projector

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
        lon, lat = proj.to_lonlat(
            str(row.get("zone", "")),
            float(net.bus_geodata.at[idx, "x"]),
            float(net.bus_geodata.at[idx, "y"]),
        )
        nodes.append(
            Node(
                id=str(row["name"]),
                name=str(row["name"]),
                type=_node_type(idx in gen_by_bus, idx in load_by_bus, is_slack),
                zone=str(row.get("zone", "")),
                lat=round(lat, 5),
                lon=round(lon, 5),
                v_nominal_kv=vn,
                is_slack=is_slack,
                min_vm_pu=lo,
                max_vm_pu=hi,
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
        lines.append(
            Line(
                id=str(row["name"]),
                name=str(row["name"]),
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


# --- what-if scenarios -------------------------------------------------------


def run_whatif(req: WhatIfRequest) -> WhatIfResponse:
    ts = store.nearest_timestamp(req.timestamp)
    base = base_frame(ts)

    net = store.read_net(ts)
    name_to_line_idx = {str(r["name"]): idx for idx, r in net.line.iterrows()}

    for lid in req.disconnect_lines:
        if lid in name_to_line_idx:
            net.line.at[name_to_line_idx[lid], "in_service"] = False

    if req.trip_nodes:
        bus_idx_by_name = {str(r["name"]): idx for idx, r in net.bus.iterrows()}
        trip_bus_idx = {bus_idx_by_name[n] for n in req.trip_nodes if n in bus_idx_by_name}
        for idx, r in net.gen.iterrows():
            if int(r["bus"]) in trip_bus_idx:
                net.gen.at[idx, "in_service"] = False
        for idx, r in net.load.iterrows():
            if int(r["bus"]) in trip_bus_idx:
                net.load.at[idx, "in_service"] = False

    if req.load_scale != 1.0:
        net.load["p_mw"] = net.load["p_mw"] * req.load_scale
        net.load["q_mvar"] = net.load["q_mvar"] * req.load_scale

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
