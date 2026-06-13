"""Phase 3 tests for the LangGraph supervisor graph."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.graph import END

from backend.agents.analyst import AnalysisOutput
from backend.agents.drafter import DraftOutput
from backend.agents.evaluator import EvalOutput
from backend.agents.researcher import ResearchOutput
from backend.graph import supervisor


def test_graph_compiles_without_error():
    assert supervisor.agentiq_graph is not None


def test_graph_has_all_expected_nodes():
    expected = {"researcher", "analyst", "drafter", "evaluator", "cost_guard", "hitl"}
    assert supervisor.NODE_NAMES == expected
    graph_nodes = set(supervisor.agentiq_graph.get_graph().nodes)
    assert expected.issubset(graph_nodes)


def test_graph_routes_researcher_to_analyst():
    assert supervisor.route_after_researcher({"error": ""}) == "analyst"


def test_graph_routes_to_end_on_error_in_researcher():
    assert supervisor.route_after_researcher({"error": "boom"}) == END


@pytest.mark.asyncio
async def test_run_pipeline_returns_agentiq_state(mocker):
    # Researcher tooling
    tavily = mocker.patch("backend.agents.researcher.TavilySearchTool")
    tavily.return_value.search = AsyncMock(return_value=[])
    scraper = mocker.patch("backend.agents.researcher.PlaywrightScraper")
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
    # score >= 0.75 -> passed -> cost_guard -> END (no HITL interrupt)
    mocker.patch("backend.agents.evaluator.run_structured",
                 AsyncMock(return_value=EvalOutput(score=0.9, feedback="good")))
    sb = MagicMock()
    sb.log_eval_result = AsyncMock(return_value={})
    mocker.patch("backend.agents.evaluator.get_supabase_client", return_value=sb)

    result = await supervisor.run_pipeline(
        {"company_name": "Acme", "website": "https://x.io", "icp_notes": "B2B SaaS"},
        run_id="run-pipeline-1",
    )
    assert isinstance(result, dict)
    # Expected state keys are present after a full pass.
    for key in ("research_output", "analysis_output", "draft_output", "eval_output"):
        assert key in result
    assert result["eval_output"]["passed"] is True
    assert not result.get("error")
