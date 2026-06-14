"""Evaluator agent: an adversarial LLM-as-judge for the drafted email."""

from __future__ import annotations

import logging

from pydantic import BaseModel, model_validator

from backend.agents._common import (
    PROMPT_CACHING_HEADER,
    cached_system,
    emit_node_event,
    get_chat_model,
    is_over_budget,
    run_structured,
)
from backend.config import get_settings
from backend.db.supabase_client import EvalResult, get_supabase_client

logger = logging.getLogger("agentiq.evaluator")

PASS_THRESHOLD = 0.75

# Deliberately adversarial — different from the drafter's constructive prompt.
_SYSTEM = (
    "You are a critical email quality evaluator. Find flaws. Be harsh. Judge the "
    "draft on personalisation, clarity, and relevance to the analyst's findings. "
    "Generic, vague, or templated emails must score low. Output scores in [0,1]."
)


class EvalOutput(BaseModel):
    score: float
    personalisation_score: float = 0.0
    clarity_score: float = 0.0
    relevance_score: float = 0.0
    feedback: str = ""
    passed: bool = False

    @model_validator(mode="after")
    def _derive_passed(self) -> "EvalOutput":
        # passed is always derived from score to stay consistent with the threshold.
        object.__setattr__(self, "passed", float(self.score) >= PASS_THRESHOLD)
        return self


async def evaluator_node(state: dict) -> dict:
    try:
        if is_over_budget(state):
            state["error"] = f"Cost limit ${get_settings().cost_limit_usd} exceeded"
            return state
        await emit_node_event(state, "evaluator", "active")
        draft = state.get("draft_output", {})
        analysis = state.get("analysis_output", {})

        human = (
            f"Analyst findings:\n{analysis}\n\n"
            f"Draft email to evaluate:\n{draft}"
        )
        # Separate instance from the drafter, with its own cached (adversarial)
        # system prompt.
        model = get_chat_model(default_headers=PROMPT_CACHING_HEADER)
        evaluation = await run_structured(model, EvalOutput, cached_system(_SYSTEM), human, state)
        state["eval_output"] = evaluation.model_dump()
        await emit_node_event(state, "evaluator", "complete", state["eval_output"])

        # Persist the eval result. Never let a logging failure crash the node.
        try:
            await get_supabase_client().log_eval_result(
                EvalResult(
                    run_id=state.get("run_id", ""),
                    agent="evaluator",
                    score=evaluation.score,
                    feedback=evaluation.feedback,
                    passed=evaluation.passed,
                )
            )
        except Exception:
            logger.exception("failed to log eval result to supabase")
    except Exception as exc:
        logger.exception("evaluator_node failed")
        state["error"] = f"evaluator failed: {exc}"
    return state
