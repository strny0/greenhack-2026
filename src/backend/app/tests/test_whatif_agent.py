from app import engine
from app.data_loader import store
from app.model import ScenarioSpec


def _first_ts() -> str:
    return store.timestamps[0]


def test_scenario_frame_is_cached_by_signature():
    ts = _first_ts()
    line_id = engine.base_frame(ts).lines[0].id
    spec_a = ScenarioSpec(disconnect_lines=[line_id])
    spec_b = ScenarioSpec(disconnect_lines=[line_id])  # equal content, new object
    f1 = engine.scenario_frame(ts, spec_a)
    f2 = engine.scenario_frame(ts, spec_b)
    assert f1 is f2  # served from cache, not re-solved


from types import SimpleNamespace

from app import agent as ag
from app.whatif_stack import Action, WhatIfStack


def _ctx(stack: WhatIfStack | None = None, simulation=None):
    """Minimal stand-in for pydantic-ai's RunContext: our helpers only read
    ctx.deps, so a SimpleNamespace carrying a Deps is enough."""
    deps = ag.Deps(timestamp=_first_ts(), simulation=simulation,
                   whatif=stack or WhatIfStack())
    return SimpleNamespace(deps=deps)


def test_effective_spec_none_when_stack_empty_and_no_sim():
    assert ag._effective_spec(_ctx()) is None


def test_frame_for_reflects_a_tripped_line():
    base = engine.base_frame(_first_ts())
    target = base.lines[0].id
    stack = WhatIfStack()
    stack.push(Action(op="trip_line", target=target))
    frame = ag._frame_for(_ctx(stack))
    tripped = next(l for l in frame.lines if l.id == target)
    assert tripped.in_service is False  # the read tools now see the hypothetical


def test_hour_override_present_when_stack_non_empty():
    stack = WhatIfStack()
    stack.push(Action(op="scale_load", factor=1.5))
    assert ag._hour_override(_ctx(stack)) is not None
    assert ag._hour_override(_ctx()) is None


def test_apply_whatif_trip_line_then_status_then_undo():
    ctx = _ctx()
    target = engine.base_frame(_first_ts()).lines[0].id

    applied = ag._apply_whatif(ctx, "trip_line", target=target, factor=None)
    assert applied["n_actions"] == 1
    assert "error" not in applied
    assert "max_loading_pct" in applied and "base" in applied["max_loading_pct"]

    status = ag._apply_whatif(ctx, "status", target=None, factor=None)
    assert status["n_actions"] == 1

    undone = ag._apply_whatif(ctx, "undo", target=None, factor=None)
    assert undone["n_actions"] == 0
    assert undone["undone"] is not None
    assert ag._effective_spec(ctx) is None  # back to the real grid


def test_apply_whatif_reset_clears_everything():
    ctx = _ctx()
    target = engine.base_frame(_first_ts()).lines[0].id
    ag._apply_whatif(ctx, "trip_line", target=target, factor=None)
    ag._apply_whatif(ctx, "scale_load", target=None, factor=1.2)
    out = ag._apply_whatif(ctx, "reset", target=None, factor=None)
    assert out["undone"] == 2
    assert out["n_actions"] == 0


def test_apply_whatif_rejects_bad_input():
    ctx = _ctx()
    assert "error" in ag._apply_whatif(ctx, "trip_line", target="no_such_line", factor=None)
    assert "error" in ag._apply_whatif(ctx, "trip_line", target=None, factor=None)
    assert "error" in ag._apply_whatif(ctx, "scale_load", target=None, factor=0)
    assert "error" in ag._apply_whatif(ctx, "frobnicate", target=None, factor=None)
    assert ctx.deps.whatif.is_empty()  # nothing got pushed


def test_what_if_tool_is_registered_and_old_signature_gone():
    names = set(ag.agent._function_toolset.tools.keys())
    assert "what_if" in names
    # the old one-shot took disconnect_lines/trip_nodes/load_scale; the new one
    # takes op/target/factor — assert the new schema is in place.
    import inspect
    sig = inspect.signature(ag._apply_whatif)
    assert list(sig.parameters)[1:] == ["op", "target", "factor"]


def test_system_prompt_documents_the_sandbox():
    p = ag.SYSTEM_PROMPT
    assert "what_if" in p
    assert "reset" in p
    # the prompt must warn that history/N-1 ignore the sandbox
    assert "n1_contingency_analysis" in p


def test_system_prompt_has_output_discipline_rules():
    p = ag.SYSTEM_PROMPT.lower()
    assert "identity" in p              # don't claim a vendor/model
    assert "ascii" in p                 # no ASCII-art charts
    assert "final answer only" in p     # no leaked planning/scratch
    assert "z-score" in p               # jargon translated, not surfaced


def test_chained_whatif_is_visible_to_other_tools_then_undone():
    ctx = _ctx()
    base_frame = engine.base_frame(_first_ts())
    busiest = max(
        (l for l in base_frame.lines if l.in_service and l.loading_pct is not None),
        key=lambda l: l.loading_pct,
    )

    # apply via the tool logic
    ag._apply_whatif(ctx, "trip_line", target=busiest.id, factor=None)

    # a DIFFERENT read path (what _frame_for feeds most_loaded_lines) must reflect it
    hypo = ag._frame_for(ctx)
    assert next(l for l in hypo.lines if l.id == busiest.id).in_service is False

    # stack a second, independent move
    other = next(l for l in base_frame.lines if l.id != busiest.id and l.in_service)
    ag._apply_whatif(ctx, "trip_line", target=other.id, factor=None)
    assert len(ctx.deps.whatif.actions) == 2

    # unwind fully
    ag._apply_whatif(ctx, "reset", target=None, factor=None)
    assert ag._effective_spec(ctx) is None
    restored = ag._frame_for(ctx)
    assert next(l for l in restored.lines if l.id == busiest.id).in_service is True
