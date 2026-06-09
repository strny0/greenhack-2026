from app.model import ScenarioSpec
from app.whatif_stack import Action, WhatIfStack, compose, has_actions


def test_push_undo_reset_and_labels():
    s = WhatIfStack()
    assert s.is_empty()
    s.push(Action(op="trip_line", target="branch_X", label="trip Line X"))
    s.push(Action(op="trip_bus", target="bus_Y", label="trip Bus Y"))
    assert not s.is_empty()
    assert s.labels() == ["trip Line X", "trip Bus Y"]
    undone = s.undo()
    assert undone.target == "bus_Y"
    assert s.labels() == ["trip Line X"]
    assert s.reset() == 1
    assert s.is_empty()
    assert s.undo() is None


def test_compose_unions_trips_from_empty_base():
    s = WhatIfStack()
    s.push(Action(op="trip_line", target="branch_A"))
    s.push(Action(op="trip_line", target="branch_A"))  # duplicate collapses
    s.push(Action(op="trip_bus", target="bus_B"))
    spec = compose(None, s)
    assert spec.disconnect_lines == ["branch_A"]
    assert spec.trip_nodes == ["bus_B"]
    assert spec.load_scale == 1.0
    assert has_actions(spec)


def test_compose_layers_on_top_of_active_simulation():
    base = ScenarioSpec(disconnect_lines=["branch_SIM"], load_scale=1.2)
    s = WhatIfStack()
    s.push(Action(op="trip_line", target="branch_A"))
    s.push(Action(op="scale_load", factor=1.5))
    spec = compose(base, s)
    assert spec.disconnect_lines == ["branch_A", "branch_SIM"]  # sorted union
    assert spec.load_scale == 1.8  # 1.2 * 1.5
    assert has_actions(spec)


def test_compose_empty_stack_no_base_has_no_actions():
    spec = compose(None, WhatIfStack())
    assert spec.disconnect_lines == []
    assert spec.trip_nodes == []
    assert spec.load_scale == 1.0
    assert not has_actions(spec)
