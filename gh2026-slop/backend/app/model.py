"""Canonical data model the frontend consumes (engine-agnostic)."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

State = Literal["ok", "warn", "alert", "offline"]
NodeType = Literal["generation", "load", "substation", "slack"]


class Node(BaseModel):
    id: str
    name: str
    label: str = ""
    type: NodeType
    zone: str
    lat: float
    lon: float
    # static
    v_nominal_kv: float
    is_slack: bool
    min_vm_pu: float
    max_vm_pu: float
    # dynamic
    vm_pu: Optional[float] = None
    vm_kv: Optional[float] = None
    va_degree: Optional[float] = None
    production_mw: float = 0.0
    consumption_mw: float = 0.0
    net_mw: float = 0.0  # production - consumption
    n_gens: int = 0
    n_loads: int = 0
    state: State = "ok"


class Line(BaseModel):
    id: str
    name: str
    label: str = ""
    from_node: str
    to_node: str
    kind: Literal["line", "trafo"] = "line"
    # static
    max_i_ka: float = 0.0
    # dynamic
    loading_pct: Optional[float] = None
    p_from_mw: Optional[float] = None
    p_to_mw: Optional[float] = None
    i_ka: Optional[float] = None
    in_service: bool = True
    state: State = "ok"


class FrameSummary(BaseModel):
    timestamp: str
    converged: bool
    total_generation_mw: float = 0.0
    total_load_mw: float = 0.0
    slack_mw: float = 0.0  # balancing power drawn from the external grid (import +)
    losses_mw: float = 0.0
    max_loading_pct: float = 0.0
    n_alerts: int = 0
    n_warnings: int = 0


class StateFrame(BaseModel):
    timestamp: str
    summary: FrameSummary
    nodes: list[Node]
    lines: list[Line]


class Alert(BaseModel):
    id: str
    severity: Literal["warn", "alert"]
    category: Literal["line_loading", "voltage", "n1_contingency"]
    element_kind: Literal["line", "node"]
    element_id: str
    message: str
    value: Optional[float] = None


class ContingencyResult(BaseModel):
    contingency_id: str  # the tripped element
    contingency_name: str
    converged: bool
    max_loading_pct: float
    n_overloads: int
    overloaded: list[dict]  # [{id, name, loading_pct}]


class WhatIfRequest(BaseModel):
    timestamp: str
    disconnect_lines: list[str] = []
    trip_nodes: list[str] = []  # bus ids whose gens/loads drop out
    load_scale: float = 1.0  # global load multiplier


class WhatIfResponse(BaseModel):
    base: StateFrame
    scenario: StateFrame
    diffs: list[dict]  # per-line loading change [{id, name, before, after, delta}]
    new_alerts: list[Alert]
