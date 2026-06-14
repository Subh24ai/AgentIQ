"""LangGraph supervisor wiring the AgentIQ pipeline together.

Flow:
    START -> researcher -> analyst -> drafter -> evaluator
    evaluator --(passed)--> cost_guard -> END
    evaluator --(failed)--> hitl
    hitl --(approved)--> gmail_send -> END   (draft good enough; send it)
    hitl --(rejected)--> drafter             (needs work; re-draft + re-evaluate)
Any agent that sets state["error"] short-circuits to END.
"""

from __future__ import annotations

import logging

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from backend.agents._common import emit_node_event
from backend.agents.analyst import analyst_node
from backend.agents.drafter import drafter_node
from backend.agents.evaluator import evaluator_node
from backend.agents.researcher import researcher_node
from backend.config import get_settings
from backend.db.redis_state import get_redis_state
from backend.db.supabase_client import OutreachLog, get_supabase_client
from backend.graph.state import AgentIQState, new_state
from backend.tools.gmail_mcp import get_gmail_client

logger = logging.getLogger("agentiq.supervisor")


# --- cost guard + hitl nodes ------------------------------------------------
async def cost_guard_node(state: dict) -> dict:
    """Abort if cumulative cost exceeds the configured limit."""

    cost = (state.get("token_usage") or {}).get("cost_usd", 0.0)
    if cost > get_settings().cost_limit_usd:
        state["error"] = "Cost limit exceeded"
        logger.warning("cost guard tripped: cost_usd=%s", cost)
    return state


async def gmail_send_node(state: dict) -> dict:
    """Send the approved draft via the Gmail client and log the outreach.

    Reached only on the HITL "approved" path. ``sent_at`` and the thread id come
    from the send confirmation — never from the call-site clock — so the outreach
    record reflects the actual send. Any failure is written to ``state["error"]``
    (not raised) so the graph routes to END gracefully.
    """

    try:
        await emit_node_event(state, "gmail_send", "active")
        client = get_gmail_client()
        recipient = (state.get("lead") or {}).get("recipient_email", "")
        draft = state.get("draft_output") or {}
        subject = draft.get("subject", "")
        body = draft.get("body", "")

        result = await client.send_email(to=recipient, subject=subject, body=body)
        state["send_result"] = {
            "message_id": result["message_id"],
            "thread_id": result["thread_id"],
            "sent_at": result["sent_at"],
            "recipient": recipient,
        }

        # Persist the outreach record. sent_at/thread_id come from the send
        # confirmation. A logging failure must not undo a real send.
        try:
            await get_supabase_client().log_outreach(
                OutreachLog(
                    run_id=state.get("run_id", ""),
                    recipient_email=recipient,
                    subject=subject,
                    body=body,
                    sent_at=result["sent_at"],
                    gmail_thread_id=result["thread_id"],
                )
            )
        except Exception:
            logger.exception("failed to log outreach to supabase")

        await emit_node_event(state, "gmail_send", "complete", state["send_result"])
    except Exception as exc:
        logger.exception("gmail_send_node failed")
        state["error"] = f"gmail_send failed: {exc}"
    return state


async def hitl_node(state: dict) -> dict:
    """Pause the graph for human review via interrupt(); resume with a decision.

    Bumps the HITL round counter *before* interrupting so the SSE generator can
    distinguish each round of the revision loop and re-emit ``hitl_required``
    for every interrupt, not only the first.
    """

    await get_redis_state().increment_hitl_round(state.get("run_id", ""))
    decision = interrupt(
        {
            "draft": state.get("draft_output", {}),
            "eval_feedback": state.get("eval_output", {}).get("feedback", ""),
            "run_id": state.get("run_id", ""),
        }
    )
    # Clear the pending payload immediately on resume so the SSE generator
    # cannot observe a stale HITL payload during resume re-execution and emit a
    # spurious hitl_required event.
    await get_redis_state().clear_hitl(state.get("run_id", ""))
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
    # approved -> the draft is good enough: send it, then END.
    # rejected -> the draft needs work: re-draft (revision loop) + re-evaluate.
    return "gmail_send" if state.get("hitl_decision") == "approved" else "drafter"


# --- graph construction -----------------------------------------------------
def build_graph() -> StateGraph:
    builder = StateGraph(AgentIQState)

    builder.add_node("researcher", researcher_node)
    builder.add_node("analyst", analyst_node)
    builder.add_node("drafter", drafter_node)
    builder.add_node("evaluator", evaluator_node)
    builder.add_node("cost_guard", cost_guard_node)
    builder.add_node("hitl", hitl_node)
    builder.add_node("gmail_send", gmail_send_node)

    builder.add_edge(START, "researcher")
    builder.add_conditional_edges("researcher", route_after_researcher, ["analyst", END])
    builder.add_conditional_edges("analyst", route_after_analyst, ["drafter", END])
    builder.add_conditional_edges("drafter", route_after_drafter, ["evaluator", END])
    builder.add_conditional_edges(
        "evaluator", route_after_evaluator, ["hitl", "cost_guard", END]
    )
    builder.add_edge("cost_guard", END)
    builder.add_conditional_edges("hitl", route_after_hitl, ["gmail_send", "drafter"])
    builder.add_edge("gmail_send", END)

    return builder


# Compiled graph with an in-memory checkpointer (required to resume after interrupt).
# NOTE: MemorySaver is process-local and not durable across restarts; swap for
# AsyncPostgresSaver (Supabase Postgres) in production.
_builder = build_graph()
agentiq_graph = _builder.compile(checkpointer=MemorySaver(), interrupt_before=[])

# Node names exposed for tests / introspection.
NODE_NAMES = {
    "researcher",
    "analyst",
    "drafter",
    "evaluator",
    "cost_guard",
    "hitl",
    "gmail_send",
}


async def run_pipeline(lead: dict, run_id: str) -> dict:
    """Invoke the pipeline for a single lead, keyed by ``run_id`` (thread_id)."""

    state = new_state(run_id=run_id, lead=lead)
    config = {"configurable": {"thread_id": run_id}}
    return await agentiq_graph.ainvoke(state, config=config)
