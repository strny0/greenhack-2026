"""Shared pickup after a trip, the operator controls (redispatch, voltage
set-point, reactive support), reserves and the N-1 worst line."""
from types import SimpleNamespace

from app import agent as ag
from app import engine
from app.data_loader import store
from app.model import ScenarioSpec, WhatIfRequest
from app.whatif_stack import Action, WhatIfStack, compose, has_actions


def _ts() -> str:
    return store.timestamps[0]


def _biggest_plant(ts: str):
    return max(engine.base_frame(ts).nodes, key=lambda n: n.production_mw)


def test_compose_merges_operator_controls():
    base = ScenarioSpec(redispatch_mw={"bus_A": 50.0})
    s = WhatIfStack()
    s.push(Action(op="redispatch", target="bus_A", factor=25.0))
    s.push(Action(op="set_voltage", target="bus_B", factor=1.1))
    s.push(Action(op="set_voltage", target="bus_B", factor=1.05))  # last one wins
    s.push(Action(op="add_reactive", target="bus_C", factor=-30.0))
    s.push(Action(op="add_reactive", target="bus_C", factor=-20.0))  # adds up
    spec = compose(base, s)
    assert spec.redispatch_mw == {"bus_A": 75.0}
    assert spec.gen_vm_pu == {"bus_B": 1.05}
    assert spec.reactive_mvar == {"bus_C": -50.0}
    assert has_actions(spec)
    assert has_actions(ScenarioSpec(gen_vm_pu={"bus_B": 1.0}))


def test_generator_trip_is_shared_not_left_to_slack():
    ts = _ts()
    plant = _biggest_plant(ts)
    res = engine.run_whatif(WhatIfRequest(timestamp=ts, trip_gens=[plant.id]))
    p = res.pickup
    assert p["imbalance_mw"] > 0
    assert abs(p["shared_mw"] + p["slack_mw"] - p["imbalance_mw"]) < 0.5
    assert p["shared_mw"] > 0.9 * p["imbalance_mw"]  # plenty of headroom here
    assert p["n_units"] > 5
    # the slack only covers losses now, so it ends well below the lost output
    assert res.scenario.summary.slack_mw < res.base.summary.slack_mw + 0.5 * plant.production_mw


def test_lowering_a_voltage_setpoint_lowers_that_bus():
    ts = _ts()
    base = engine.base_frame(ts)
    gen_bus = next(n for n in base.nodes if n.production_mw > 50 and (n.vm_pu or 0) > 1.05)
    f = engine.scenario_frame(ts, ScenarioSpec(gen_vm_pu={gen_bus.id: 1.0}))
    after = next(n for n in f.nodes if n.id == gen_bus.id)
    assert f.summary.converged
    assert after.vm_pu < gen_bus.vm_pu - 0.03


def test_reactor_lowers_voltage_at_a_load_bus():
    ts = _ts()
    base = engine.base_frame(ts)
    load_bus = next(n for n in base.nodes if not n.production_mw and not n.is_slack and n.vm_pu)
    f = engine.scenario_frame(ts, ScenarioSpec(reactive_mvar={load_bus.id: -150.0}))
    after = next(n for n in f.nodes if n.id == load_bus.id)
    assert after.vm_pu < load_bus.vm_pu


def test_redispatch_moves_that_plant():
    ts = _ts()
    plant = _biggest_plant(ts)
    f = engine.scenario_frame(ts, ScenarioSpec(redispatch_mw={plant.id: -100.0}))
    after = next(n for n in f.nodes if n.id == plant.id)
    assert abs((plant.production_mw - after.production_mw) - 100.0) < 1.0


def test_reserves_shrink_after_a_trip():
    ts = _ts()
    plant = _biggest_plant(ts)
    before = engine.reserves(ts)
    after = engine.reserves(ts, ScenarioSpec(trip_gens=[plant.id]))
    assert before["spinning_reserve_mw"] > 0
    assert after["spinning_reserve_mw"] < before["spinning_reserve_mw"]
    assert after["pickup"]["imbalance_mw"] > 0
    assert before["largest_online_plant"]["bus"] == plant.id


def test_n1_rows_name_the_worst_line():
    rows = [r for r in engine.run_n1(_ts()) if r.converged]
    assert rows and all(r.worst_line_id for r in rows)
    assert all(r.worst_line_id != r.contingency_id for r in rows)


def test_agent_whatif_controls_validate_and_stack():
    ctx = SimpleNamespace(deps=ag.Deps(timestamp=_ts(), whatif=WhatIfStack()))
    plant = _biggest_plant(_ts())
    assert "error" in ag._apply_whatif(ctx, "set_voltage", target=plant.id, factor=1.5)
    assert "error" in ag._apply_whatif(ctx, "redispatch", target="bus_nope", factor=10)
    out = ag._apply_whatif(ctx, "set_voltage", target=plant.id, factor=1.05)
    assert out["n_actions"] == 1 and "voltage set-point" in out["stack"][0]
    out = ag._apply_whatif(ctx, "trip_gen", target=plant.id, factor=None)
    assert out["pickup"]["shared_by_units_mw"] > 0
