"""Phase 6 tests for the standalone eval framework (external calls mocked)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.agents.analyst import AnalysisOutput
from backend.agents.drafter import DraftOutput
from backend.agents.evaluator import EvalOutput
from backend.agents.researcher import ResearchOutput
from backend.eval.judge import AgentIQEvaluator, EvalSuiteResult
from tests.eval_fixtures import ALL_CASES


def _research_se(*args, **_kw):
    return ResearchOutput(company_summary="profile", tech_stack=["python"])


def _analyst_se(*args, **_kw):
    human = args[3].lower()
    low = "consumer" in human
    return AnalysisOutput(
        fit_score=0.2 if low else 0.9,
        fit_reasoning="weak consumer fit" if low else "strong data fit",
    )


def _drafter_se(*args, **_kw):
    human = args[3].lower()
    low = "consumer" in human
    body = "Generic outreach note." if low else "We can help your data team scale."
    return DraftOutput(subject="Hi", body=body)


def _evaluator_se(*args, **_kw):
    human = args[3].lower()
    return EvalOutput(score=0.9 if "data" in human else 0.4, feedback="judged")


async def _run_suite(mocker) -> EvalSuiteResult:
    # Mock researcher tooling
    tv = mocker.patch("backend.agents.researcher.TavilySearchTool")
    tv.return_value.search = AsyncMock(return_value=[])
    sc = mocker.patch("backend.agents.researcher.PlaywrightScraper")
    sc.return_value.scrape = AsyncMock(return_value="")
    for mod in ("researcher", "analyst", "drafter", "evaluator"):
        mocker.patch(f"backend.agents.{mod}.get_chat_model", return_value=MagicMock())
    mocker.patch("backend.agents.researcher.run_structured", AsyncMock(side_effect=_research_se))
    mocker.patch("backend.agents.analyst.run_structured", AsyncMock(side_effect=_analyst_se))
    mocker.patch("backend.agents.drafter.run_structured", AsyncMock(side_effect=_drafter_se))
    mocker.patch("backend.agents.evaluator.run_structured", AsyncMock(side_effect=_evaluator_se))
    sb = MagicMock()
    sb.log_eval_result = AsyncMock(return_value={})
    mocker.patch("backend.agents.evaluator.get_supabase_client", return_value=sb)

    return await AgentIQEvaluator().run_eval_suite(ALL_CASES)


@pytest.mark.asyncio
async def test_eval_suite_runs_all_cases(mocker):
    result = await _run_suite(mocker)
    assert result.total == 3
    assert len(result.cases) == 3


@pytest.mark.asyncio
async def test_high_fit_case_passes(mocker):
    result = await _run_suite(mocker)
    high = result.cases[0]
    assert high.company_name.startswith("Northwind")
    assert high.passed is True
    assert high.fit_score >= 0.7


@pytest.mark.asyncio
async def test_low_fit_case_fails_or_scores_low(mocker):
    result = await _run_suite(mocker)
    low = result.cases[1]
    assert low.passed is False or low.fit_score < 0.5


@pytest.mark.asyncio
async def test_injection_case_is_blocked_before_eval(mocker):
    result = await _run_suite(mocker)
    injection = result.cases[2]
    assert injection.blocked is True


@pytest.mark.asyncio
async def test_ragas_faithfulness_score_is_float(mocker):
    result = await _run_suite(mocker)
    assert isinstance(result.cases[0].faithfulness, float)
    assert isinstance(result.cases[0].answer_relevancy, float)


@pytest.mark.asyncio
async def test_eval_suite_result_counts_match_cases(mocker):
    result = await _run_suite(mocker)
    assert result.total == len(ALL_CASES)
    assert result.passed + result.failed == result.total
