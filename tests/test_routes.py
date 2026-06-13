"""Phase 4 tests for the FastAPI run routes (external calls mocked)."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from backend.api.main import app
from backend.security.auth import create_access_token

ADMIN = {"Authorization": f"Bearer {create_access_token({'sub': 'admin', 'role': 'admin'})}"}
REVIEWER = {"Authorization": f"Bearer {create_access_token({'sub': 'reviewer', 'role': 'reviewer'})}"}

VALID_BODY = {
    "company_name": "Acme",
    "website": "https://example.com",
    "icp_notes": "B2B SaaS",
    "recipient_email": "test@test.com",
}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _fake_supabase(mocker, **methods):
    fake = MagicMock()
    for name in ("create_run", "get_run", "list_runs", "update_run_status", "log_hitl_review"):
        setattr(fake, name, AsyncMock(return_value=methods.get(name)))
    mocker.patch("backend.api.routes.get_supabase_client", return_value=fake)
    return fake


@pytest.mark.asyncio
async def test_post_runs_requires_auth(mocker):
    _fake_supabase(mocker)
    async with _client() as c:
        r = await c.post("/runs", json=VALID_BODY)
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_post_runs_returns_run_id(mocker):
    _fake_supabase(mocker, create_run={"id": "x"})
    mocker.patch(
        "backend.graph.supervisor.run_pipeline",
        AsyncMock(return_value={"token_usage": {}, "analysis_output": {}, "draft_output": {}, "eval_output": {}, "error": ""}),
    )
    async with _client() as c:
        r = await c.post("/runs", json=VALID_BODY, headers=ADMIN)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "started"
    assert len(data["run_id"]) > 0


@pytest.mark.asyncio
async def test_get_run_returns_404_for_unknown_id(mocker):
    _fake_supabase(mocker, get_run=None)
    async with _client() as c:
        r = await c.get("/runs/does-not-exist", headers=ADMIN)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_hitl_endpoint_requires_reviewer_role(mocker):
    _fake_supabase(mocker)
    async with _client() as c:
        r = await c.post("/runs/abc/hitl", json={"decision": "approved", "feedback": "ok"}, headers=ADMIN)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_hitl_endpoint_rejects_invalid_decision_value(mocker):
    _fake_supabase(mocker)
    async with _client() as c:
        r = await c.post("/runs/abc/hitl", json={"decision": "maybe", "feedback": "x"}, headers=REVIEWER)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_stream_endpoint_returns_event_stream_content_type(mocker):
    _fake_supabase(mocker)
    # Seed a terminal "complete" event so the generator emits it and returns
    # promptly (otherwise the SSE poll loop would run until its safety cap).
    from backend.api.routes import RUN_COMPLETE_NODE
    from backend.db.redis_state import get_redis_state

    run_id = "stream-test-run"
    await get_redis_state().append_event(
        run_id, {"node": RUN_COMPLETE_NODE, "status": "complete", "partial_output": {}}
    )
    token = create_access_token({"sub": "admin", "role": "admin"})
    async with _client() as c:
        async with c.stream("GET", f"/runs/{run_id}/stream?token={token}") as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = await resp.aread()
    assert "event: complete" in body.decode()


@pytest.mark.asyncio
async def test_runs_list_is_paginated(mocker):
    fake = _fake_supabase(mocker, list_runs=[{"id": "a"}])
    async with _client() as c:
        r = await c.get("/runs?limit=5&offset=10", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 5 and body["offset"] == 10
    assert body["runs"] == [{"id": "a"}]
    fake.list_runs.assert_awaited_once_with(limit=5, offset=10)


@pytest.mark.asyncio
async def test_post_runs_validates_website_is_url(mocker):
    _fake_supabase(mocker)
    bad = {**VALID_BODY, "website": "not-a-url"}
    async with _client() as c:
        r = await c.post("/runs", json=bad, headers=ADMIN)
    assert r.status_code == 422
