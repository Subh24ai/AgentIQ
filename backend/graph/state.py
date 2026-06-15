"""Typed LangGraph state for the AgentIQ pipeline.

The state is a TypedDict because LangGraph passes it node-to-node and merges
returned partial dicts into the running state. The ``messages`` field uses
``Annotated[list, operator.add]`` so that LangGraph accumulates message lists
returned by each node instead of overwriting them.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class AgentIQState(TypedDict, total=False):
    """Shared state threaded through every node of the AgentIQ graph.

    ``total=False`` lets nodes return partial updates; LangGraph merges them.
    Use :func:`new_state` to construct a fully-defaulted instance.
    """

    run_id: str
    lead: dict                 # raw input: company_name, website, icp_notes
    research_output: dict      # populated by Researcher agent
    analysis_output: dict      # populated by Analyst agent; includes fit_score 0.0-1.0
    draft_output: dict         # populated by Drafter agent; subject, body, reasoning
    eval_output: dict          # populated by Evaluator agent; score, feedback
    hitl_decision: str         # "approved" | "rejected" | "pending"
    hitl_feedback: str         # human's free-text feedback if rejected
    revision_count: int        # default 0 — increments each time drafter is re-run after HITL reject
    send_result: dict          # populated by gmail_send_node; {} if not sent
    error: str                 # last error message if any agent failed
    token_usage: dict          # cumulative {input_tokens, output_tokens, total_tokens,
                               #             cache_read_tokens, cache_creation_tokens, cost_usd}
    messages: Annotated[list, operator.add]  # LangGraph message list for tracing


# Fields that must always be present with a sensible default when a run starts.
REQUIRED_FIELDS: tuple[str, ...] = (
    "run_id",
    "lead",
    "research_output",
    "analysis_output",
    "draft_output",
    "eval_output",
    "hitl_decision",
    "hitl_feedback",
    "revision_count",
    "send_result",
    "error",
    "token_usage",
    "messages",
)


def new_state(run_id: str = "", lead: dict | None = None) -> AgentIQState:
    """Build an :class:`AgentIQState` with every field defaulted.

    ``hitl_decision`` defaults to ``"pending"`` and ``token_usage`` /
    ``messages`` default to empty containers so downstream nodes can rely on
    their presence without ``KeyError`` guards.
    """

    return AgentIQState(
        run_id=run_id,
        lead=lead or {},
        research_output={},
        analysis_output={},
        draft_output={},
        eval_output={},
        hitl_decision="pending",
        hitl_feedback="",
        revision_count=0,
        send_result={},
        error="",
        token_usage={
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "cost_usd": 0.0,
        },
        messages=[],
    )
