"""Analyst agent: scores ICP fit and extracts personalization angles."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field, field_validator

from backend.agents._common import (
    emit_node_event,
    get_chat_model,
    is_over_budget,
    run_structured,
)
from backend.config import get_settings

logger = logging.getLogger("agentiq.analyst")

_SYSTEM = (
    "You are a B2B sales analyst. Given a company research profile and an Ideal "
    "Customer Profile (ICP), judge how well the company fits, surface concrete "
    "personalization hooks, recommend a tone, and flag any reasons NOT to reach out. "
    "fit_score must be a float between 0.0 and 1.0."
)


class AnalysisOutput(BaseModel):
    fit_score: float
    fit_reasoning: str = ""
    personalization_hooks: list[str] = Field(default_factory=list)
    recommended_tone: str = "formal"  # "formal" | "casual" | "technical"
    red_flags: list[str] = Field(default_factory=list)

    @field_validator("fit_score")
    @classmethod
    def _clamp_fit_score(cls, v: float) -> float:
        f = float(v)
        if f < 0.0 or f > 1.0:
            clamped = max(0.0, min(1.0, f))
            logger.warning("fit_score %s out of range; clamped to %s", f, clamped)
            return clamped
        return f


async def analyst_node(state: dict) -> dict:
    try:
        if is_over_budget(state):
            state["error"] = f"Cost limit ${get_settings().cost_limit_usd} exceeded"
            return state
        await emit_node_event(state, "analyst", "active")
        research = state.get("research_output", {})
        icp_notes = state.get("lead", {}).get("icp_notes", "")

        human = (
            f"ICP notes:\n{icp_notes}\n\n"
            f"Company research profile:\n{research}"
        )
        model = get_chat_model()
        analysis = await run_structured(model, AnalysisOutput, _SYSTEM, human, state)
        state["analysis_output"] = analysis.model_dump()
        await emit_node_event(state, "analyst", "complete", state["analysis_output"])
    except Exception as exc:
        logger.exception("analyst_node failed")
        state["error"] = f"analyst failed: {exc}"
    return state
