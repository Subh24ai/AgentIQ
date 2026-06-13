"""Async Supabase client wrapper for AgentIQ persistence.

A thin singleton over supabase-py's async client. Every public method accepts a
validated Pydantic model so callers cannot persist malformed rows. The
underlying async client is created lazily on first use so that importing this
module (e.g. during tests) never requires live Supabase credentials.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field
from supabase import AsyncClient, acreate_client

from backend.config import get_settings


# ---------------------------------------------------------------------------
# Validation models (one per write path)
# ---------------------------------------------------------------------------
class RunCreate(BaseModel):
    run_id: str
    lead: dict[str, Any]
    status: str = "started"
    token_usage: dict[str, Any] = Field(default_factory=dict)


class RunStatusUpdate(BaseModel):
    run_id: str
    status: str
    token_usage: Optional[dict[str, Any]] = None


class OutreachLog(BaseModel):
    run_id: str
    recipient_email: str
    subject: str
    body: str
    sent_at: Optional[str] = None
    gmail_thread_id: Optional[str] = None


class HITLReview(BaseModel):
    run_id: str
    eval_score: Optional[float] = None
    draft: dict[str, Any] = Field(default_factory=dict)
    decision: Optional[str] = None
    reviewer_notes: Optional[str] = None
    reviewed_at: Optional[str] = None


class EvalResult(BaseModel):
    run_id: str
    agent: str
    score: Optional[float] = None
    feedback: Optional[str] = None
    passed: Optional[bool] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SupabaseClient:
    """Singleton wrapper around the supabase-py async client."""

    _instance: Optional["SupabaseClient"] = None

    def __new__(cls) -> "SupabaseClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = None
        return cls._instance

    async def _get_client(self) -> AsyncClient:
        """Lazily create and cache the async Supabase client."""

        if self._client is None:
            settings = get_settings()
            self._client = await acreate_client(
                settings.supabase_url, settings.supabase_anon_key
            )
        return self._client

    # --- write paths ------------------------------------------------------
    async def create_run(self, run: RunCreate) -> dict[str, Any]:
        client = await self._get_client()
        row = {
            "id": run.run_id,
            "lead": run.lead,
            "status": run.status,
            "token_usage": run.token_usage,
        }
        resp = await client.table("runs").insert(row).execute()
        return resp.data[0] if resp.data else row

    async def update_run_status(self, update: RunStatusUpdate) -> dict[str, Any]:
        client = await self._get_client()
        patch: dict[str, Any] = {"status": update.status}
        if update.token_usage is not None:
            patch["token_usage"] = update.token_usage
        resp = (
            await client.table("runs")
            .update(patch)
            .eq("id", update.run_id)
            .execute()
        )
        return resp.data[0] if resp.data else patch

    async def log_outreach(self, entry: OutreachLog) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.table("outreach_log").insert(entry.model_dump()).execute()
        return resp.data[0] if resp.data else entry.model_dump()

    async def log_hitl_review(self, review: HITLReview) -> dict[str, Any]:
        client = await self._get_client()
        payload = review.model_dump()
        payload.setdefault("created_at", _now_iso())
        resp = await client.table("hitl_reviews").insert(payload).execute()
        return resp.data[0] if resp.data else payload

    async def log_eval_result(self, result: EvalResult) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.table("eval_results").insert(result.model_dump()).execute()
        return resp.data[0] if resp.data else result.model_dump()

    # --- read paths -------------------------------------------------------
    async def get_run(self, run_id: str) -> Optional[dict[str, Any]]:
        client = await self._get_client()
        resp = await client.table("runs").select("*").eq("id", run_id).execute()
        return resp.data[0] if resp.data else None

    async def list_runs(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        client = await self._get_client()
        resp = (
            await client.table("runs")
            .select("*")
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return resp.data or []


def get_supabase_client() -> SupabaseClient:
    """Return the SupabaseClient singleton."""

    return SupabaseClient()
