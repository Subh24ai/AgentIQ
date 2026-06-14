# Native Claude-as-judge eval — replaces RAGAS which is incompatible
# with langchain-community>=0.4.0 due to removed vertexai submodule.
# Implements equivalent Faithfulness and Answer Relevancy metrics.
# Advantage: no external eval framework dependency, full control over
# judge prompts, auditable scoring logic.
"""Standalone evaluation framework for AgentIQ (separate from the in-pipeline
Evaluator agent). Runs the full graph per case and scores the draft with two
Claude-as-judge metrics:

- **Faithfulness** — are the draft's claims grounded in the research output?
- **Answer Relevancy** — does the draft speak to the ICP / personalization hooks?
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from backend.config import get_settings
from backend.db.supabase_client import EvalResult, get_supabase_client
from backend.tools.search import BLOCKED_CONTENT

logger = logging.getLogger("agentiq.eval")

PASS_THRESHOLD = 0.7


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class EvalCase(BaseModel):
    lead: dict[str, Any]
    expected_fit_score_min: float
    expected_topics_in_draft: list[str] = Field(default_factory=list)
    should_pass_hitl: bool


class NativeEvalMetrics(BaseModel):
    faithfulness: float
    answer_relevancy: float
    faithfulness_reasoning: str = ""
    relevancy_reasoning: str = ""


class EvalCaseResult(BaseModel):
    case_id: str
    passed: bool
    metrics: NativeEvalMetrics
    error: str = ""


class EvalSuiteResult(BaseModel):
    total: int
    passed: int
    failed: int
    avg_faithfulness: float
    avg_relevancy: float
    cases: list[EvalCaseResult] = Field(default_factory=list)


_FAITHFULNESS_PROMPT = (
    "Given this research context:\n{research}\n\n"
    "And this email draft:\n{draft}\n\n"
    "Score from 0.0 to 1.0 how faithfully the draft's claims are supported by the "
    "research. 1.0 = all claims grounded. 0.0 = draft makes up facts not in research. "
    'Return ONLY a JSON object: {{"faithfulness": <float>, "reasoning": <str>}}'
)

_RELEVANCY_PROMPT = (
    "Given these ICP notes:\n{icp}\n\n"
    "And these personalization hooks:\n{hooks}\n\n"
    "And this email draft:\n{draft}\n\n"
    "Score from 0.0 to 1.0 how relevant and personalized the draft is to the ICP. "
    "1.0 = highly targeted. 0.0 = completely generic. "
    'Return ONLY a JSON object: {{"answer_relevancy": <float>, "reasoning": <str>}}'
)


def _parse_json(content: Any) -> dict:
    """Parse a JSON object from a model response, tolerating ```json fences."""

    text = content if isinstance(content, str) else str(content)
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def _clamp(v: Any) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


class AgentIQEvaluator:
    """Runs an eval suite over the full pipeline using Claude as the judge."""

    def __init__(self) -> None:
        self.llm = ChatAnthropic(
            model="claude-sonnet-4-6",
            anthropic_api_key=get_settings().anthropic_api_key,
        )

    async def score_faithfulness(
        self, research_output: dict, draft_body: str
    ) -> tuple[float, str]:
        prompt = _FAITHFULNESS_PROMPT.format(research=research_output, draft=draft_body)
        resp = await self.llm.ainvoke([HumanMessage(content=prompt)])
        data = _parse_json(getattr(resp, "content", ""))
        return _clamp(data.get("faithfulness", 0.0)), str(data.get("reasoning", ""))

    async def score_relevancy(
        self, icp_notes: str, personalization_hooks: list[str], draft_body: str
    ) -> tuple[float, str]:
        prompt = _RELEVANCY_PROMPT.format(
            icp=icp_notes, hooks=personalization_hooks, draft=draft_body
        )
        resp = await self.llm.ainvoke([HumanMessage(content=prompt)])
        data = _parse_json(getattr(resp, "content", ""))
        return _clamp(data.get("answer_relevancy", 0.0)), str(data.get("reasoning", ""))

    async def evaluate_case(
        self, test_case: EvalCase, pipeline_result: dict
    ) -> EvalCaseResult:
        case_id = str(test_case.lead.get("company_name", "case"))[:40]
        research = pipeline_result.get("research_output", {}) or {}
        analysis = pipeline_result.get("analysis_output", {}) or {}
        draft = pipeline_result.get("draft_output", {}) or {}
        draft_body = str(draft.get("body", ""))
        icp = str(test_case.lead.get("icp_notes", ""))
        hooks = analysis.get("personalization_hooks", []) or []

        # If the pipeline blocked the lead (injection) or produced no draft, the
        # case is a hard fail — don't waste a judge call on empty content.
        blocked = (
            not draft_body
            or BLOCKED_CONTENT in str(research)
            or bool(pipeline_result.get("error"))
        )
        if blocked:
            return EvalCaseResult(
                case_id=case_id,
                passed=False,
                metrics=NativeEvalMetrics(
                    faithfulness=0.0,
                    answer_relevancy=0.0,
                    faithfulness_reasoning="skipped",
                    relevancy_reasoning="skipped",
                ),
                error="pipeline blocked or produced no draft",
            )

        faithfulness, f_reason = await self.score_faithfulness(research, draft_body)
        relevancy, r_reason = await self.score_relevancy(icp, hooks, draft_body)
        metrics = NativeEvalMetrics(
            faithfulness=faithfulness,
            answer_relevancy=relevancy,
            faithfulness_reasoning=f_reason,
            relevancy_reasoning=r_reason,
        )
        passed = faithfulness >= PASS_THRESHOLD and relevancy >= PASS_THRESHOLD

        try:
            await get_supabase_client().log_eval_result(
                EvalResult(
                    run_id=str(pipeline_result.get("run_id", "")),
                    agent="native_judge",
                    score=round((faithfulness + relevancy) / 2, 4),
                    feedback=f_reason,
                    passed=passed,
                )
            )
        except Exception:
            logger.warning("failed to log native eval result to supabase", exc_info=True)

        return EvalCaseResult(case_id=case_id, passed=passed, metrics=metrics)

    async def _run_pipeline(self, case: EvalCase, index: int) -> dict:
        from backend.graph.supervisor import run_pipeline

        return await run_pipeline(case.lead, run_id=f"eval-{index}")

    async def run_eval_suite(self, test_cases: list[EvalCase]) -> EvalSuiteResult:
        async def _one(case: EvalCase, i: int) -> EvalCaseResult:
            result = await self._run_pipeline(case, i)
            return await self.evaluate_case(case, result)

        cases = await asyncio.gather(
            *(_one(case, i) for i, case in enumerate(test_cases))
        )
        cases = list(cases)
        passed = sum(1 for c in cases if c.passed)
        n = len(cases) or 1
        avg_f = round(sum(c.metrics.faithfulness for c in cases) / n, 4)
        avg_r = round(sum(c.metrics.answer_relevancy for c in cases) / n, 4)
        return EvalSuiteResult(
            total=len(cases),
            passed=passed,
            failed=len(cases) - passed,
            avg_faithfulness=avg_f,
            avg_relevancy=avg_r,
            cases=cases,
        )
