"""Phase 6 tests for the native Claude-as-judge eval framework (LLM calls mocked)."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.eval.judge import AgentIQEvaluator
from tests.eval_fixtures import ALL_CASES, HIGH_FIT, INJECTION, LOW_FIT


def _result(*, research=True, draft="We help your data team scale with our platform.", error="", run_id="r"):
    """A pipeline_result (AgentIQState-shaped dict) for the judge to score."""
    return {
        "run_id": run_id,
        "research_output": {"company_summary": "Acme builds data tooling"} if research else {},
        "analysis_output": {"personalization_hooks": ["data team"]},
        "draft_output": {"subject": "Hi", "body": draft},
        "eval_output": {},
        "error": error,
    }


def _mock_judge(evaluator, faithfulness: float, relevancy: float):
    """Mock the evaluator's LLM so both judge calls return controlled JSON."""
    msg = MagicMock()
    msg.content = json.dumps(
        {"faithfulness": faithfulness, "answer_relevancy": relevancy, "reasoning": "because"}
    )
    evaluator.llm = MagicMock()
    evaluator.llm.ainvoke = AsyncMock(return_value=msg)


def _mock_supabase(mocker):
    sb = MagicMock()
    sb.log_eval_result = AsyncMock(return_value={})
    mocker.patch("backend.eval.judge.get_supabase_client", return_value=sb)


@pytest.mark.asyncio
async def test_eval_suite_runs_all_cases(mocker):
    _mock_supabase(mocker)
    mocker.patch("backend.graph.supervisor.run_pipeline", AsyncMock(return_value=_result()))
    evaluator = AgentIQEvaluator()
    _mock_judge(evaluator, 0.9, 0.9)
    result = await evaluator.run_eval_suite(ALL_CASES)
    assert result.total == 3
    assert len(result.cases) == 3


@pytest.mark.asyncio
async def test_high_fit_case_passes(mocker):
    _mock_supabase(mocker)
    evaluator = AgentIQEvaluator()
    _mock_judge(evaluator, 0.85, 0.80)
    res = await evaluator.evaluate_case(HIGH_FIT, _result())
    assert res.passed is True


@pytest.mark.asyncio
async def test_low_fit_case_scores_low(mocker):
    _mock_supabase(mocker)
    evaluator = AgentIQEvaluator()
    _mock_judge(evaluator, 0.4, 0.3)
    res = await evaluator.evaluate_case(LOW_FIT, _result())
    assert res.passed is False


@pytest.mark.asyncio
async def test_injection_case_returns_error_or_low_score(mocker):
    from backend.tools.search import BLOCKED_CONTENT

    _mock_supabase(mocker)
    evaluator = AgentIQEvaluator()
    _mock_judge(evaluator, 0.9, 0.9)  # high mock, but blocked path must override

    # Exercise the BLOCKED_CONTENT branch specifically: research carries the real
    # firewall marker while the draft is non-empty and no error is set, so the
    # marker is the only thing that can trip the blocked path.
    blocked_result = {
        "run_id": "inj",
        "research_output": {"company_summary": BLOCKED_CONTENT},
        "analysis_output": {"personalization_hooks": []},
        "draft_output": {"subject": "Hi", "body": "A non-empty draft body."},
        "eval_output": {},
        "error": "",
    }
    res = await evaluator.evaluate_case(INJECTION, blocked_result)
    assert res.error != ""
    assert res.metrics.faithfulness < 0.5
    assert res.passed is False


@pytest.mark.asyncio
async def test_faithfulness_score_is_between_0_and_1(mocker):
    _mock_supabase(mocker)
    evaluator = AgentIQEvaluator()
    _mock_judge(evaluator, 0.75, 0.75)
    res = await evaluator.evaluate_case(HIGH_FIT, _result())
    assert 0.0 <= res.metrics.faithfulness <= 1.0
    assert res.metrics.faithfulness > 0  # non-vacuous: 0.0 would be a hidden failure


@pytest.mark.asyncio
async def test_relevancy_score_is_between_0_and_1(mocker):
    _mock_supabase(mocker)
    evaluator = AgentIQEvaluator()
    _mock_judge(evaluator, 0.75, 0.75)
    res = await evaluator.evaluate_case(HIGH_FIT, _result())
    assert 0.0 <= res.metrics.answer_relevancy <= 1.0
    assert res.metrics.answer_relevancy > 0  # non-vacuous
