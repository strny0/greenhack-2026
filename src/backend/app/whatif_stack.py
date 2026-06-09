"""The agent's chainable what-if state — a pure, dataset-free model.

An ``Action`` is one operator move (trip a line, trip a bus, scale load). A
``WhatIfStack`` is the ordered list the agent builds up and unwinds. ``compose``
folds the operator's active simulation (if any) plus the stack into a single
``ScenarioSpec`` the engine already knows how to solve — trips union, load scales
multiply. Kept import-light (only ``app.model``) so it stays trivially testable
and the agent's frame-routing can call it without dragging in the solver.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .model import ScenarioSpec

VALID_OPS = ("trip_line", "trip_bus", "scale_load")


@dataclass
class Action:
    """One hypothetical move on the stack. ``target`` is a line/bus id for the
    trip ops; ``factor`` is the multiplier for ``scale_load``. ``label`` is the
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
        if self.op == "scale_load":
            return f"scale load x{self.factor}"
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
    ``stack`` into one effective ScenarioSpec. Trips union; load scales multiply."""
    lines = set(base.disconnect_lines) if base else set()
    nodes = set(base.trip_nodes) if base else set()
    scale = base.load_scale if base else 1.0
    for a in stack.actions:
        if a.op == "trip_line" and a.target:
            lines.add(a.target)
        elif a.op == "trip_bus" and a.target:
            nodes.add(a.target)
        elif a.op == "scale_load" and a.factor:
            scale *= a.factor
    return ScenarioSpec(
        preset="agent_whatif",
        label="; ".join(stack.labels()) or (base.label if base else ""),
        disconnect_lines=sorted(lines),
        trip_nodes=sorted(nodes),
        load_scale=round(scale, 6),
    )


def has_actions(spec: ScenarioSpec) -> bool:
    """True when the spec actually changes the grid (so it needs a re-solve)."""
    return bool(spec.disconnect_lines or spec.trip_nodes or spec.load_scale != 1.0)
