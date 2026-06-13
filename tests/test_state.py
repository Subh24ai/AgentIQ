"""Phase 1 tests for the AgentIQState typed state."""

from backend.graph.state import REQUIRED_FIELDS, AgentIQState, new_state


def test_state_has_all_required_fields():
    state = new_state(run_id="run-1", lead={"company_name": "Acme"})
    for field in REQUIRED_FIELDS:
        assert field in state, f"missing required field: {field}"
    # The TypedDict annotations should declare every required field too.
    for field in REQUIRED_FIELDS:
        assert field in AgentIQState.__annotations__


def test_token_usage_defaults_to_zeroed_counters():
    state = new_state()
    usage = state["token_usage"]
    assert isinstance(usage, dict)
    # Correct UsageMetadata-aligned keys, all zero at the start of a run.
    assert usage["input_tokens"] == 0
    assert usage["output_tokens"] == 0
    assert usage["total_tokens"] == 0
    assert usage["cache_read_tokens"] == 0
    assert usage["cache_creation_tokens"] == 0
    assert usage["cost_usd"] == 0.0


def test_hitl_decision_default_is_pending():
    state = new_state()
    assert state["hitl_decision"] == "pending"


def test_messages_field_is_list():
    state = new_state()
    assert isinstance(state["messages"], list)
    assert state["messages"] == []


def test_analysis_output_fit_score_type_is_float():
    # Simulate an Analyst node writing a fit_score that arrives as a string and
    # must be coerced to float before use downstream.
    state = new_state()
    state["analysis_output"] = {"fit_score": "0.85"}
    coerced = float(state["analysis_output"]["fit_score"])
    assert isinstance(coerced, float)
    assert coerced == 0.85
