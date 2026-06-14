"""AgentIQ run API: create runs, stream progress over SSE, and resume HITL."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel, HttpUrl
from starlette.responses import StreamingResponse

from backend.db.redis_state import get_redis_state
from backend.db.supabase_client import (
    HITLReview,
    RunCreate,
    RunStatusUpdate,
    get_supabase_client,
)
from backend.security.auth import require_role, verify_token
from backend.security.injection_guard import PromptInjectionGuard

logger = logging.getLogger("agentiq.routes")

router = APIRouter(tags=["runs"])

POLL_INTERVAL_SECONDS = 1.0
MAX_STREAM_SECONDS = 600  # safety cap so a stream never hangs forever
RUN_COMPLETE_NODE = "__complete__"


# --- request/response models ------------------------------------------------
class RunRequest(BaseModel):
    company_name: str
    website: HttpUrl
    icp_notes: str
    recipient_email: str


class HITLRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    feedback: str = ""


# --- background execution ---------------------------------------------------
async def _publish_terminal(run_id: str, result: Any) -> None:
    """Publish the outcome of a (possibly resumed) graph invocation to Redis.

    If the graph paused again on an interrupt, mark HITL pending; otherwise emit
    the terminal ``complete`` event so any open SSE stream finishes cleanly.
    Shared by the background run and the HITL resume path.
    """

    rs = get_redis_state()
    interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
    if interrupts:
        payload = getattr(interrupts[0], "value", {}) or {}
        await rs.set_hitl_pending(run_id, payload)
        return

    token_usage = result.get("token_usage", {}) if isinstance(result, dict) else {}
    await rs.append_event(
        run_id,
        {
            "node": RUN_COMPLETE_NODE,
            "status": "complete",
            "partial_output": {
                "analysis_output": result.get("analysis_output", {}),
                "draft_output": result.get("draft_output", {}),
                "eval_output": result.get("eval_output", {}),
                "send_result": result.get("send_result", {}),
                "error": result.get("error", ""),
            },
            "token_usage": token_usage,
        },
    )
    await rs.set_node_status(run_id, "complete")
    try:
        await get_supabase_client().update_run_status(
            RunStatusUpdate(run_id=run_id, status="complete", token_usage=token_usage)
        )
    except Exception:
        logger.warning("update_run_status failed for %s", run_id, exc_info=True)


async def _execute_run(run_id: str, lead: dict) -> None:
    """Run the pipeline in the background and publish terminal state to Redis."""

    # Imported lazily so importing this module doesn't pull in the LLM stack.
    from backend.graph.supervisor import run_pipeline

    rs = get_redis_state()
    try:
        result = await run_pipeline(lead, run_id)
        await _publish_terminal(run_id, result)
    except Exception:
        logger.exception("background run %s failed", run_id)
        await rs.append_event(
            run_id, {"node": RUN_COMPLETE_NODE, "status": "error", "partial_output": {}}
        )


# --- endpoints --------------------------------------------------------------
@router.post("/runs")
async def create_run(
    body: RunRequest,
    background: BackgroundTasks,
    claims: dict = Depends(verify_token),
) -> dict[str, str]:
    # OWASP LLM01: firewall direct user input before it enters the pipeline.
    guard = PromptInjectionGuard()
    for field_name, field_value in [
        ("company_name", body.company_name),
        ("icp_notes", body.icp_notes),
    ]:
        scan = guard.scan(field_value)
        if not scan.is_safe:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Input rejected: potential prompt injection",
                    "field": field_name,
                    "matched_patterns": scan.matched_patterns,
                    "risk_score": scan.risk_score,
                },
            )

    run_id = str(uuid.uuid4())
    lead = {
        "company_name": body.company_name,
        "website": str(body.website),
        "icp_notes": body.icp_notes,
        "recipient_email": body.recipient_email,
    }
    try:
        await get_supabase_client().create_run(
            RunCreate(run_id=run_id, lead=lead, status="started")
        )
    except Exception:
        logger.warning("create_run persistence failed for %s", run_id, exc_info=True)

    background.add_task(_execute_run, run_id, lead)
    return {"run_id": run_id, "status": "started"}


def _sse(event: str, data: dict[str, Any]) -> str:
    # The `event:` line keeps the stream valid SSE; the `data:` line carries a
    # self-describing {event, data} object so a fetch()/ReadableStream client can
    # dispatch without relying on the EventSource event-type parsing.
    payload = json.dumps({"event": event, "data": data})
    return f"event: {event}\ndata: {payload}\n\n"


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: str, current_user: dict = Depends(verify_token)
) -> StreamingResponse:
    rs = get_redis_state()

    async def event_generator():
        start = time.time()
        offset = 0
        hitl_round = 0
        try:
            while time.time() - start < MAX_STREAM_SECONDS:
                events = await rs.get_events_since(run_id, offset)
                for event in events:
                    offset += 1
                    if event.get("node") == RUN_COMPLETE_NODE:
                        yield _sse(
                            "complete",
                            {"run_id": run_id, "final_state": event.get("partial_output", {})},
                        )
                        return
                    yield _sse("update", event)

                # The revision loop can interrupt multiple times. The round
                # counter advances on every interrupt, so re-emit hitl_required
                # for each new round (not just the first). Only advance our local
                # round once the payload is present, to avoid racing the bump.
                current_round = await rs.get_hitl_round(run_id)
                if current_round > hitl_round:
                    hitl = await rs.get_hitl_pending(run_id)
                    if hitl:
                        yield _sse(
                            "hitl_required",
                            {
                                "run_id": run_id,
                                "draft": hitl.get("draft", {}),
                                "eval_feedback": hitl.get("eval_feedback", ""),
                            },
                        )
                        hitl_round = current_round

                await asyncio.sleep(POLL_INTERVAL_SECONDS)
            # Hit the safety cap without a terminal event.
            yield _sse("timeout", {"run_id": run_id})
        except asyncio.CancelledError:
            # Client disconnected. Re-raise so FastAPI closes the response cleanly.
            logger.info(json.dumps({"event": "sse_client_disconnected", "run_id": run_id}))
            raise
        finally:
            logger.info(
                json.dumps(
                    {
                        "event": "sse_generator_closed",
                        "run_id": run_id,
                        "elapsed_s": round(time.time() - start, 1),
                    }
                )
            )

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/runs/{run_id}/hitl")
async def submit_hitl(
    run_id: str,
    body: HITLRequest,
    claims: dict = Depends(require_role("reviewer")),
) -> dict[str, str]:
    from langgraph.types import Command

    from backend.graph.supervisor import agentiq_graph

    rs = get_redis_state()
    config = {"configurable": {"thread_id": run_id}}

    # Log the decision FIRST so it is durable even if the resume fails. The
    # timestamp is taken here (at log time), never from the graph result — that
    # result may not exist if the resume raises.
    reviewed_at = datetime.utcnow().isoformat() + "Z"
    try:
        await get_supabase_client().log_hitl_review(
            HITLReview(
                run_id=run_id,
                decision=body.decision,
                reviewer_notes=body.feedback,
                reviewed_at=reviewed_at,
            )
        )
    except Exception:
        logger.warning("log_hitl_review failed for %s", run_id, exc_info=True)

    # Resume the graph separately. A failure here does not lose the decision
    # (already logged above); surface that explicitly to the caller.
    try:
        result = await agentiq_graph.ainvoke(
            Command(resume={"decision": body.decision, "feedback": body.feedback}),
            config=config,
        )
    except Exception as e:
        logger.error(
            json.dumps(
                {"event": "hitl_resume_failed", "run_id": run_id, "error": str(e)}
            )
        )
        raise HTTPException(
            status_code=500,
            detail="Graph resume failed. Decision was logged.",
        )

    await rs.clear_hitl(run_id)
    # Publish the post-resume outcome so the open SSE stream reaches completion
    # (or re-prompts for HITL if the revision loop produced another interrupt).
    await _publish_terminal(run_id, result)

    return {"status": "resumed", "decision": body.decision}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, claims: dict = Depends(verify_token)) -> dict:
    record = await get_supabase_client().get_run(run_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return record


@router.get("/runs")
async def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    claims: dict = Depends(verify_token),
) -> dict:
    runs = await get_supabase_client().list_runs(limit=limit, offset=offset)
    return {"runs": runs, "limit": limit, "offset": offset}
