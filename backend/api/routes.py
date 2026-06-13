"""AgentIQ run API: create runs, stream progress over SSE, and resume HITL."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Literal, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    status,
)
from jose import JWTError, jwt
from pydantic import BaseModel, HttpUrl
from starlette.responses import StreamingResponse

from backend.config import get_settings
from backend.db.redis_state import get_redis_state
from backend.db.supabase_client import (
    HITLReview,
    RunCreate,
    RunStatusUpdate,
    get_supabase_client,
)
from backend.security.auth import ALGORITHM, require_role, verify_token

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
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _stream_auth(
    token: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> dict:
    """Auth for the SSE endpoint: accept token via query param (EventSource can't
    set headers) or via the Authorization bearer header."""

    raw = token
    if not raw and authorization and authorization.lower().startswith("bearer "):
        raw = authorization.split(" ", 1)[1]
    if not raw:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        return jwt.decode(raw, get_settings().jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str, claims: dict = Depends(_stream_auth)) -> StreamingResponse:
    rs = get_redis_state()

    async def event_generator():
        offset = 0
        hitl_sent = False
        elapsed = 0.0
        while elapsed < MAX_STREAM_SECONDS:
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

            if not hitl_sent:
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
                    hitl_sent = True

            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            elapsed += POLL_INTERVAL_SECONDS

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
    try:
        result = await agentiq_graph.ainvoke(
            Command(resume={"decision": body.decision, "feedback": body.feedback}),
            config=config,
        )
    except Exception:
        logger.exception("failed to resume graph for run %s", run_id)
        raise HTTPException(status_code=409, detail="Run is not awaiting HITL review")

    await rs.clear_hitl(run_id)
    # Publish the post-resume outcome so the open SSE stream reaches completion
    # (or re-prompts for HITL if the revision loop produced another interrupt).
    await _publish_terminal(run_id, result)
    try:
        await get_supabase_client().log_hitl_review(
            HITLReview(
                run_id=run_id,
                decision=body.decision,
                reviewer_notes=body.feedback,
            )
        )
    except Exception:
        logger.warning("log_hitl_review failed for %s", run_id, exc_info=True)

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
