"""The agent's chainable what-if state — a pure, dataset-free model.

An ``Action`` is one operator move (trip a line, a bus or a plant, scale load,
redispatch a plant, change a voltage set-point, add reactive support). A
``WhatIfStack`` is the ordered list the agent builds up and unwinds. ``compose``
folds the operator's active simulation (if any) plus the stack into a single
``ScenarioSpec`` the engine already knows how to solve — trips union, load scales
multiply, redispatch and reactive support add up per bus, and the latest voltage
set-point per bus wins. Kept import-light (only ``app.model``) so it stays trivially testable
and the agent's frame-routing can call it without dragging in the solver.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .model import ScenarioSpec

VALID_OPS = ("trip_line", "trip_bus", "trip_gen", "scale_load", "redispatch", "set_voltage", "add_reactive")


@dataclass
class Action:
    """One hypothetical move on the stack. ``target`` is a line/bus id for the
    trip ops and the bus for the controls; ``factor`` is the multiplier for
    ``scale_load``, MW for ``redispatch``, p.u. for ``set_voltage`` and Mvar
    (+ injects, - absorbs) for ``add_reactive``. ``label`` is the
    operator-facing description shown back to the model."""

    op: str
    target: str | None = None
    factor: float | None = None
    label: str = ""

    def display(self) -> str:
        if self.label:
            return self.label
        if self.op == "trip_line":
            return f"trip line {self.target}"
        if self.op == "trip_bus":
            return f"trip bus {self.target}"
        if self.op == "trip_gen":
            return f"trip generation at {self.target}"
        if self.op == "scale_load":
            return f"scale load x{self.factor}"
        if self.op == "redispatch":
            return f"redispatch {self.target} {self.factor:+g} MW"
        if self.op == "set_voltage":
            return f"set voltage at {self.target} to {self.factor:g} p.u."
        if self.op == "add_reactive":
            return f"reactive support at {self.target} {self.factor:+g} Mvar"
        return self.op


@dataclass
class WhatIfStack:
    """Ordered, mutable list of hypothetical actions for one conversation turn."""

    actions: list[Action] = field(default_factory=list)

    def push(self, action: Action) -> None:
        self.actions.append(action)

    def undo(self) -> Action | None:
        return self.actions.pop() if self.actions else None

    def reset(self) -> int:
        n = len(self.actions)
        self.actions.clear()
        return n

    def is_empty(self) -> bool:
        return not self.actions

    def labels(self) -> list[str]:
        return [a.display() for a in self.actions]


def compose(base: ScenarioSpec | None, stack: WhatIfStack) -> ScenarioSpec:
    """Fold the operator's active sim (``base``, may be None) and the agent's
    ``stack`` into one effective ScenarioSpec. Trips union; load scales multiply;
    redispatch and reactive support add per bus; the last voltage set-point wins."""
    lines = set(base.disconnect_lines) if base else set()
    nodes = set(base.trip_nodes) if base else set()
    gens = set(base.trip_gens) if base else set()
    scale = base.load_scale if base else 1.0
    vm = dict(base.gen_vm_pu) if base else {}
    q = dict(base.reactive_mvar) if base else {}
    rd = dict(base.redispatch_mw) if base else {}
    for a in stack.actions:
        if a.op == "trip_line" and a.target:
            lines.add(a.target)
        elif a.op == "trip_bus" and a.target:
            nodes.add(a.target)
        elif a.op == "trip_gen" and a.target:
            gens.add(a.target)
        elif a.op == "scale_load" and a.factor:
            scale *= a.factor
        elif a.op == "set_voltage" and a.target and a.factor:
            vm[a.target] = a.factor
        elif a.op == "add_reactive" and a.target and a.factor:
            q[a.target] = q.get(a.target, 0.0) + a.factor
        elif a.op == "redispatch" and a.target and a.factor:
            rd[a.target] = rd.get(a.target, 0.0) + a.factor
    return ScenarioSpec(
        preset="agent_whatif",
        label="; ".join(stack.labels()) or (base.label if base else ""),
        disconnect_lines=sorted(lines),
        trip_nodes=sorted(nodes),
        trip_gens=sorted(gens),
        load_scale=round(scale, 6),
        gen_vm_pu=vm,
        reactive_mvar=q,
        redispatch_mw=rd,
    )


def has_actions(spec: ScenarioSpec) -> bool:
    """True when the spec actually changes the grid (so it needs a re-solve)."""
    return bool(
        spec.disconnect_lines or spec.trip_nodes or spec.trip_gens or spec.load_scale != 1.0
        or spec.gen_vm_pu or spec.reactive_mvar or spec.redispatch_mw
    )
