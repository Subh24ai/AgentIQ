"""Drafter agent: writes the personalized outreach email.

Uses Anthropic prompt caching via the ``anthropic-beta`` header so the (large,
stable) system prompt is cached across calls.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, field_validator

from backend.agents._common import (
    PROMPT_CACHING_HEADER,
    cached_system,
    emit_node_event,
    get_chat_model,
    run_structured,
)

logger = logging.getLogger("agentiq.drafter")

MAX_WORDS = 200

_SYSTEM = (
    "You are an expert B2B cold-email copywriter. Using the company research and "
    "the analyst's personalization hooks, write a concise, specific, non-generic "
    "outreach email. Plain text only, no markdown. The body must be at most 200 "
    "words. Lead with a personalized hook, state value clearly, and end with one "
    "low-friction call to action."
)

_SENTENCE_END_RE = re.compile(r"[.!?]")


def _truncate_to_word_limit(text: str, limit: int = MAX_WORDS) -> str:
    """Truncate to <= ``limit`` words, ending at the last sentence boundary."""

    words = text.split()
    if len(words) <= limit:
        return text
    truncated = " ".join(words[:limit])
    # Cut back to the last sentence-ending punctuation, if any.
    matches = list(_SENTENCE_END_RE.finditer(truncated))
    if matches:
        return truncated[: matches[-1].end()].strip()
    return truncated.strip()


class DraftOutput(BaseModel):
    subject: str
    body: str
    reasoning: str = ""
    estimated_open_rate: str = ""

    @field_validator("body")
    @classmethod
    def _enforce_word_limit(cls, v: str) -> str:
        return _truncate_to_word_limit(v, MAX_WORDS)


async def drafter_node(state: dict) -> dict:
    try:
        await emit_node_event(state, "drafter", "active")
        analysis = state.get("analysis_output", {})
        research = state.get("research_output", {})

        human = (
            f"Analyst output:\n{analysis}\n\n"
            f"Company research:\n{research}\n\n"
            f"Incorporate feedback if present:\n{state.get('hitl_feedback', '')}"
        )
        model = get_chat_model(default_headers=PROMPT_CACHING_HEADER)
        # Pass the system prompt as a cache_control content block so Anthropic
        # caches this stable prefix across drafter calls.
        draft = await run_structured(model, DraftOutput, cached_system(_SYSTEM), human, state)
        state["draft_output"] = draft.model_dump()
        await emit_node_event(state, "drafter", "complete", state["draft_output"])
    except Exception as exc:
        logger.exception("drafter_node failed")
        state["error"] = f"drafter failed: {exc}"
    return state
