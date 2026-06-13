"""LangGraph supervisor wiring the AgentIQ pipeline together.

Flow:
    START -> researcher -> analyst -> drafter -> evaluator
    evaluator --(passed)--> cost_guard -> END
    evaluator --(failed)--> hitl
    hitl --(approved)--> drafter        (loop for revision)
    hitl --(rejected)--> END
Any agent that sets state["error"] short-circuits to END.
"""

from __future__ import annotations

import logging

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from backend.agents.analyst import analyst_node
from backend.agents.drafter import drafter_node
from backend.agents.evaluator import evaluator_node
from backend.agents.researcher import researcher_node
from backend.config import get_settings
from backend.graph.state import AgentIQState, new_state

logger = logging.getLogger("agentiq.supervisor")


# --- cost guard + hitl nodes ------------------------------------------------
async def cost_guard_node(state: dict) -> dict:
    """Abort if cumulative cost exceeds the configured limit."""

    cost = (state.get("token_usage") or {}).get("cost_usd", 0.0)
    if cost > get_settings().cost_limit_usd:
        state["error"] = "Cost limit exceeded"
        logger.warning("cost guard tripped: cost_usd=%s", cost)
    return state


def hitl_node(state: dict) -> dict:
    """Pause the graph for human review via interrupt(); resume with a decision."""

    decision = interrupt(
        {
            "draft": state.get("draft_output", {}),
            "eval_feedback": state.get("eval_output", {}).get("feedback", ""),
            "run_id": state.get("run_id", ""),
        }
    )
    # `decision` is the value passed to Command(resume=...).
    state["hitl_decision"] = decision.get("decision", "pending")
    state["hitl_feedback"] = decision.get("feedback", "")
    return state


# --- routing functions ------------------------------------------------------
def route_after_researcher(state: dict) -> str:
    return END if state.get("error") else "analyst"


def route_after_analyst(state: dict) -> str:
    return END if state.get("error") else "drafter"


def route_after_drafter(state: dict) -> str:
    return END if state.get("error") else "evaluator"


def route_after_evaluator(state: dict) -> str:
    if state.get("error"):
        return END
    passed = (state.get("eval_output") or {}).get("passed", False)
    return "cost_guard" if passed else "hitl"


def route_after_hitl(state: dict) -> str:
    # Per spec: approved -> back to drafter (revision loop); rejected -> END.
    return "drafter" if state.get("hitl_decision") == "approved" else END


# --- graph construction -----------------------------------------------------
def build_graph() -> StateGraph:
    builder = StateGraph(AgentIQState)

    builder.add_node("researcher", researcher_node)
    builder.add_node("analyst", analyst_node)
    builder.add_node("drafter", drafter_node)
    builder.add_node("evaluator", evaluator_node)
    builder.add_node("cost_guard", cost_guard_node)
    builder.add_node("hitl", hitl_node)

    builder.add_edge(START, "researcher")
    builder.add_conditional_edges("researcher", route_after_researcher, ["analyst", END])
    builder.add_conditional_edges("analyst", route_after_analyst, ["drafter", END])
    builder.add_conditional_edges("drafter", route_after_drafter, ["evaluator", END])
    builder.add_conditional_edges(
        "evaluator", route_after_evaluator, ["hitl", "cost_guard", END]
    )
    builder.add_edge("cost_guard", END)
    builder.add_conditional_edges("hitl", route_after_hitl, ["drafter", END])

    return builder


# Compiled graph with an in-memory checkpointer (required to resume after interrupt).
# NOTE: MemorySaver is process-local and not durable across restarts; swap for
# AsyncPostgresSaver (Supabase Postgres) in production.
_builder = build_graph()
agentiq_graph = _builder.compile(checkpointer=MemorySaver(), interrupt_before=[])

# Node names exposed for tests / introspection.
NODE_NAMES = {"researcher", "analyst", "drafter", "evaluator", "cost_guard", "hitl"}


async def run_pipeline(lead: dict, run_id: str) -> dict:
    """Invoke the pipeline for a single lead, keyed by ``run_id`` (thread_id)."""

    state = new_state(run_id=run_id, lead=lead)
    config = {"configurable": {"thread_id": run_id}}
    return await agentiq_graph.ainvoke(state, config=config)
