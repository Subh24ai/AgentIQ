"""Phase 3 tests for the LangGraph supervisor graph."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.graph import END

from backend.agents.analyst import AnalysisOutput
from backend.agents.drafter import DraftOutput
from backend.agents.evaluator import EvalOutput
from backend.agents.researcher import ResearchOutput
from backend.graph import supervisor
from backend.graph.state import new_state


def test_graph_compiles_without_error():
    assert supervisor.agentiq_graph is not None


def test_graph_has_all_expected_nodes():
    expected = {"researcher", "analyst", "drafter", "evaluator", "cost_guard", "hitl", "gmail_send"}
    assert supervisor.NODE_NAMES == expected
    graph_nodes = set(supervisor.agentiq_graph.get_graph().nodes)
    assert expected.issubset(graph_nodes)


def test_graph_routes_researcher_to_analyst():
    assert supervisor.route_after_researcher({"error": ""}) == "analyst"


def test_graph_routes_to_end_on_error_in_researcher():
    assert supervisor.route_after_researcher({"error": "boom"}) == END


# --- HITL routing semantics + gmail_send node ------------------------------
def _send_state() -> dict:
    state = new_state(
        run_id="run-send",
        lead={
            "company_name": "Acme",
            "website": "https://x.io",
            "icp_notes": "B2B SaaS",
            "recipient_email": "founder@acme.com",
        },
    )
    state["draft_output"] = {"subject": "Hi there", "body": "Short personalized body."}
    return state


def _mock_send(mocker, *, message_id="msg-1", thread_id="thr-1", sent_at="2000-01-01T00:00:00+00:00"):
    """Patch the gmail client and supabase client used by gmail_send_node."""
    client = MagicMock()
    client.send_email = AsyncMock(
        return_value={"message_id": message_id, "thread_id": thread_id, "sent_at": sent_at}
    )
    mocker.patch("backend.graph.supervisor.get_gmail_client", return_value=client)
    sb = MagicMock()
    sb.log_outreach = AsyncMock(return_value={})
    mocker.patch("backend.graph.supervisor.get_supabase_client", return_value=sb)
    return client, sb


def test_approved_hitl_routes_to_gmail_send():
    assert supervisor.route_after_hitl({"hitl_decision": "approved"}) == "gmail_send"


def test_rejected_hitl_routes_to_drafter():
    assert supervisor.route_after_hitl({"hitl_decision": "rejected"}) == "drafter"


# --- cost_guard now sends passing drafts (cost_guard -> gmail_send) ----------
def test_cost_guard_routes_to_gmail_send_not_end():
    # A passing draft within budget must be sent, not dead-ended at END.
    assert supervisor.route_after_cost_guard({"error": ""}) == "gmail_send"


def test_cost_guard_routes_to_end_when_error_set():
    # If the cost guard tripped (error set), short-circuit to END, never send.
    assert supervisor.route_after_cost_guard({"error": "Cost limit exceeded"}) == END


def test_cost_guard_edge_targets_gmail_send():
    # The compiled graph must contain a cost_guard -> gmail_send edge.
    edges = {(e.source, e.target) for e in supervisor.agentiq_graph.get_graph().edges}
    assert ("cost_guard", "gmail_send") in edges


@pytest.mark.asyncio
async def test_gmail_send_node_calls_send_email(mocker):
    client, _ = _mock_send(mocker)
    state = await supervisor.gmail_send_node(_send_state())

    client.send_email.assert_awaited_once_with(
        to="founder@acme.com", subject="Hi there", body="Short personalized body."
    )
    assert state["send_result"]["message_id"] == "msg-1"
    assert state["send_result"]["thread_id"] == "thr-1"
    assert state["send_result"]["recipient"] == "founder@acme.com"
    assert state["error"] == ""


@pytest.mark.asyncio
async def test_gmail_send_node_logs_outreach_before_returning(mocker):
    _, sb = _mock_send(mocker)
    state = await supervisor.gmail_send_node(_send_state())

    sb.log_outreach.assert_awaited_once()
    logged = sb.log_outreach.call_args.args[0]
    assert logged.run_id == "run-send"
    assert logged.recipient_email == "founder@acme.com"
    assert logged.subject == "Hi there"
    assert logged.gmail_thread_id == "thr-1"
    # The node returned a populated send_result alongside the persisted log.
    assert state["send_result"]["message_id"] == "msg-1"


@pytest.mark.asyncio
async def test_gmail_send_node_sets_sent_at_from_result_not_clock(mocker):
    fixed_sent_at = "1999-12-31T23:59:59+00:00"
    _, sb = _mock_send(mocker, sent_at=fixed_sent_at)
    state = await supervisor.gmail_send_node(_send_state())

    # sent_at must come from the send confirmation, never datetime.utcnow().
    assert state["send_result"]["sent_at"] == fixed_sent_at
    logged = sb.log_outreach.call_args.args[0]
    assert logged.sent_at == fixed_sent_at


@pytest.mark.asyncio
async def test_run_pipeline_returns_agentiq_state(mocker):
    # Researcher tooling
    tavily = mocker.patch("backend.agents.researcher.TavilySearchTool")
    tavily.return_value.search = AsyncMock(return_value=[])
    scraper = mocker.patch("backend.agents.researcher.HttpxScraper")
    scraper.return_value.scrape = AsyncMock(return_value="")

    # All chat models + structured calls mocked so no network / no LLM
    for mod in ("researcher", "analyst", "drafter", "evaluator"):
        mocker.patch(f"backend.agents.{mod}.get_chat_model", return_value=MagicMock())
    mocker.patch("backend.agents.researcher.run_structured",
                 AsyncMock(return_value=ResearchOutput(company_summary="s")))
    mocker.patch("backend.agents.analyst.run_structured",
                 AsyncMock(return_value=AnalysisOutput(fit_score=0.8)))
    mocker.patch("backend.agents.drafter.run_structured",
                 AsyncMock(return_value=DraftOutput(subject="Hi", body="Short body.")))
    # score >= 0.75 -> passed -> cost_guard -> gmail_send -> END (no HITL interrupt)
    mocker.patch("backend.agents.evaluator.run_structured",
                 AsyncMock(return_value=EvalOutput(score=0.9, feedback="good")))
    sb = MagicMock()
    sb.log_eval_result = AsyncMock(return_value={})
    mocker.patch("backend.agents.evaluator.get_supabase_client", return_value=sb)
    # The passing path now reaches gmail_send; mock the send + outreach log.
    _mock_send(mocker)

    result = await supervisor.run_pipeline(
        {"company_name": "Acme", "website": "https://x.io", "icp_notes": "B2B SaaS",
         "recipient_email": "founder@acme.com"},
        run_id="run-pipeline-1",
    )
    assert isinstance(result, dict)
    # Expected state keys are present after a full pass.
    for key in ("research_output", "analysis_output", "draft_output", "eval_output"):
        assert key in result
    assert result["eval_output"]["passed"] is True
    assert not result.get("error")


@pytest.mark.asyncio
async def test_happy_path_routes_to_gmail_send(mocker):
    """A passing eval within budget must reach gmail_send and actually send."""
    tavily = mocker.patch("backend.agents.researcher.TavilySearchTool")
    tavily.return_value.search = AsyncMock(return_value=[])
    scraper = mocker.patch("backend.agents.researcher.HttpxScraper")
    scraper.return_value.scrape = AsyncMock(return_value="")

    for mod in ("researcher", "analyst", "drafter", "evaluator"):
        mocker.patch(f"backend.agents.{mod}.get_chat_model", return_value=MagicMock())
    mocker.patch("backend.agents.researcher.run_structured",
                 AsyncMock(return_value=ResearchOutput(company_summary="s")))
    mocker.patch("backend.agents.analyst.run_structured",
                 AsyncMock(return_value=AnalysisOutput(fit_score=0.8)))
    mocker.patch("backend.agents.drafter.run_structured",
                 AsyncMock(return_value=DraftOutput(subject="Hi", body="Short body.")))
    # passed=True -> cost_guard -> gmail_send (no HITL).
    mocker.patch("backend.agents.evaluator.run_structured",
                 AsyncMock(return_value=EvalOutput(score=0.9, feedback="good")))
    eval_sb = MagicMock()
    eval_sb.log_eval_result = AsyncMock(return_value={})
    mocker.patch("backend.agents.evaluator.get_supabase_client", return_value=eval_sb)

    gmail, _ = _mock_send(mocker)

    result = await supervisor.run_pipeline(
        {
            "company_name": "Acme",
            "website": "https://x.io",
            "icp_notes": "B2B SaaS",
            "recipient_email": "founder@acme.com",
        },
        run_id="run-happy-send",
    )

    # The passing draft was sent via gmail_send, not dead-ended at END.
    gmail.send_email.assert_awaited_once_with(
        to="founder@acme.com", subject="Hi", body="Short body."
    )
    assert result["send_result"]["recipient"] == "founder@acme.com"
    assert result["eval_output"]["passed"] is True
    assert not result.get("error")


# --- revision-count cap on the HITL reject loop -----------------------------
def _mock_hitl_redis(mocker):
    rs = MagicMock()
    rs.increment_hitl_round = AsyncMock(return_value=1)
    rs.clear_hitl = AsyncMock(return_value=None)
    mocker.patch("backend.graph.supervisor.get_redis_state", return_value=rs)
    return rs


@pytest.mark.asyncio
async def test_revision_count_increments_on_hitl_reject(mocker):
    """Three rejections bump revision_count to 3 and route the graph to END."""
    _mock_hitl_redis(mocker)
    # interrupt() returns the reviewer's resume payload — here, a rejection.
    mocker.patch(
        "backend.graph.supervisor.interrupt",
        return_value={"decision": "rejected", "feedback": "no", "edited_body": ""},
    )

    state = new_state(run_id="rev-reject")
    assert state["revision_count"] == 0

    # Re-run the hitl node once per reject cycle (drafter -> evaluator -> hitl).
    for _ in range(3):
        state = await supervisor.hitl_node(state)

    assert state["revision_count"] == 3
    # The cap is the FIRST check in the router, so it short-circuits to END...
    assert supervisor.route_after_hitl(state) == END
    # ...and the terminal error is set (in the node, so it persists to final state).
    assert state["error"] == "Max revisions reached (3). Run terminated."


@pytest.mark.asyncio
async def test_revision_count_does_not_increment_on_hitl_approve(mocker):
    """An approval leaves revision_count at 0 and routes to gmail_send."""
    _mock_hitl_redis(mocker)
    mocker.patch(
        "backend.graph.supervisor.interrupt",
        return_value={"decision": "approved", "feedback": "", "edited_body": ""},
    )

    state = new_state(run_id="rev-approve")
    state = await supervisor.hitl_node(state)

    assert state["revision_count"] == 0
    assert state["error"] == ""
    assert supervisor.route_after_hitl(state) == "gmail_send"
