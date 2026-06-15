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


_NO_PENDING = object()  # sentinel so callers can pass pending=None explicitly


def _mock_redis_pending(mocker, pending=_NO_PENDING):
    """Patch routes.get_redis_state so submit_hitl's pending check is controlled.

    Default: a non-empty payload (run is awaiting review). Pass pending=None to
    simulate a run that is not interrupted, or a side_effect list for sequences.
    """
    if pending is _NO_PENDING:
        pending = {"draft": {"subject": "s", "body": "b"}, "eval_feedback": "x"}
    rs = MagicMock()
    if isinstance(pending, list):
        rs.get_hitl_pending = AsyncMock(side_effect=pending)
    else:
        rs.get_hitl_pending = AsyncMock(return_value=pending)
    rs.clear_hitl = AsyncMock(return_value=None)
    rs.append_event = AsyncMock(return_value=None)
    rs.set_node_status = AsyncMock(return_value=None)
    rs.set_hitl_pending = AsyncMock(return_value=None)
    rs.get_hitl_round = AsyncMock(return_value=0)
    rs.increment_hitl_round = AsyncMock(return_value=0)
    # A live review window by default (age marker present); resume is allowed.
    rs.get_hitl_age_seconds = AsyncMock(return_value=12.0)
    mocker.patch("backend.api.routes.get_redis_state", return_value=rs)
    return rs


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
    """reviewer and admin may approve HITL; any other role is rejected (403)."""
    _fake_supabase(mocker)
    _mock_redis_pending(mocker)  # run is awaiting review
    mocker.patch(
        "backend.graph.supervisor.agentiq_graph.ainvoke",
        AsyncMock(
            return_value={
                "token_usage": {},
                "analysis_output": {},
                "draft_output": {},
                "eval_output": {},
                "error": "",
            }
        ),
    )
    guest = {
        "Authorization": f"Bearer {create_access_token({'sub': 'g', 'role': 'guest'})}"
    }
    async with _client() as c:
        # admin is now permitted to approve HITL (role gate passes -> 200).
        r_admin = await c.post(
            "/runs/abc/hitl", json={"decision": "approved", "feedback": "ok"}, headers=ADMIN
        )
        # a role that is neither reviewer nor admin is rejected.
        r_guest = await c.post(
            "/runs/abc/hitl", json={"decision": "approved", "feedback": "ok"}, headers=guest
        )
    assert r_admin.status_code == 200
    assert r_guest.status_code == 403


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
    headers = {"Authorization": f"Bearer {token}"}
    async with _client() as c:
        async with c.stream("GET", f"/runs/{run_id}/stream", headers=headers) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = await resp.aread()
    assert "event: complete" in body.decode()


@pytest.mark.asyncio
async def test_stream_endpoint_requires_bearer_not_query_param(mocker):
    """SSE auth is bearer-header only now; the ?token= query param is rejected."""
    _fake_supabase(mocker)
    from backend.api.routes import RUN_COMPLETE_NODE
    from backend.db.redis_state import get_redis_state

    run_id = "bearer-stream"
    token = create_access_token({"sub": "admin", "role": "admin"})

    # Query param alone (no Authorization header) is no longer accepted.
    async with _client() as c:
        r = await c.get(f"/runs/{run_id}/stream?token={token}")
    assert r.status_code == 401

    # Bearer header authenticates; seed a terminal event so it returns promptly.
    await get_redis_state().append_event(
        run_id, {"node": RUN_COMPLETE_NODE, "status": "complete", "partial_output": {}}
    )
    async with _client() as c:
        async with c.stream(
            "GET",
            f"/runs/{run_id}/stream",
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            body = await resp.aread()
    assert "event: complete" in body.decode()


@pytest.mark.asyncio
async def test_hitl_logs_before_resuming_graph(mocker):
    """The HITL decision must be persisted BEFORE the graph is resumed, so a
    resume failure can never lose the decision."""
    fake = _fake_supabase(mocker)
    _mock_redis_pending(mocker)  # run is awaiting review

    order: list[str] = []

    async def _log(*_a, **_k):
        order.append("log")
        return {}

    async def _update(*_a, **_k):
        order.append("update")
        return {}

    async def _ainvoke(*_a, **_k):
        order.append("ainvoke")
        return {
            "token_usage": {},
            "analysis_output": {},
            "draft_output": {},
            "eval_output": {},
            "error": "",
        }

    fake.log_hitl_review = AsyncMock(side_effect=_log)
    fake.update_run_status = AsyncMock(side_effect=_update)
    mocker.patch(
        "backend.graph.supervisor.agentiq_graph.ainvoke", AsyncMock(side_effect=_ainvoke)
    )

    async with _client() as c:
        r = await c.post(
            "/runs/order-test/hitl",
            json={"decision": "approved", "feedback": "ok"},
            headers=REVIEWER,
        )

    assert r.status_code == 200
    # Real ordering assertion: the log happened strictly before the resume.
    assert "log" in order and "ainvoke" in order
    assert order.index("log") < order.index("ainvoke")


@pytest.mark.asyncio
async def test_second_hitl_round_is_streamed_to_client(mocker):
    """The revision loop interrupts more than once; each round must be streamed."""
    _fake_supabase(mocker)
    from backend.api.routes import RUN_COMPLETE_NODE

    fake_rs = MagicMock()
    # Two empty event polls (so the HITL check runs twice), then a terminal event.
    fake_rs.get_events_since = AsyncMock(
        side_effect=[
            [],
            [],
            [{"node": RUN_COMPLETE_NODE, "status": "complete", "partial_output": {}}],
        ]
    )
    # Round counter advances 1 -> 2 across the two polls (new interrupt each time).
    fake_rs.get_hitl_round = AsyncMock(side_effect=[1, 2, 2])
    fake_rs.get_hitl_pending = AsyncMock(
        return_value={"draft": {"subject": "s"}, "eval_feedback": "needs work"}
    )
    mocker.patch("backend.api.routes.get_redis_state", return_value=fake_rs)
    # Don't actually wait between polls.
    mocker.patch("backend.api.routes.asyncio.sleep", AsyncMock())

    token = create_access_token({"sub": "admin", "role": "admin"})
    async with _client() as c:
        async with c.stream(
            "GET",
            "/runs/round-test/stream",
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            assert resp.status_code == 200
            body = (await resp.aread()).decode()

    assert body.count("event: hitl_required") == 2
    assert "event: complete" in body


@pytest.mark.asyncio
async def test_hitl_round_increments_in_hitl_node(mocker):
    """The hitl node must bump the round counter before interrupting."""
    from backend.graph import supervisor

    fake_rs = MagicMock()
    fake_rs.increment_hitl_round = AsyncMock(return_value=1)
    fake_rs.clear_hitl = AsyncMock(return_value=None)
    mocker.patch("backend.graph.supervisor.get_redis_state", return_value=fake_rs)
    # Stand in for LangGraph's interrupt() so the node runs to completion.
    mocker.patch(
        "backend.graph.supervisor.interrupt",
        return_value={"decision": "approved", "feedback": ""},
    )

    state = {"run_id": "node-round", "draft_output": {}, "eval_output": {}}
    out = await supervisor.hitl_node(state)

    fake_rs.increment_hitl_round.assert_awaited_once_with("node-round")
    assert out["hitl_decision"] == "approved"


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


@pytest.mark.asyncio
async def test_post_runs_rejects_invalid_email(mocker):
    _fake_supabase(mocker)
    bad = {**VALID_BODY, "recipient_email": "notanemail"}
    async with _client() as c:
        r = await c.post("/runs", json=bad, headers=ADMIN)
    assert r.status_code == 422


def _capture_resume(mocker):
    """Patch the graph resume and capture the Command passed to ainvoke."""
    captured: dict = {}

    async def _ainvoke(cmd, *_a, **_k):
        captured["cmd"] = cmd
        return {
            "token_usage": {},
            "analysis_output": {},
            "draft_output": {},
            "eval_output": {},
            "error": "",
        }

    mocker.patch(
        "backend.graph.supervisor.agentiq_graph.ainvoke", AsyncMock(side_effect=_ainvoke)
    )
    return captured


@pytest.mark.asyncio
async def test_hitl_edited_body_is_passed_to_resume(mocker):
    """The reviewer's edited body must reach the graph in the resume payload."""
    _fake_supabase(mocker)
    _mock_redis_pending(mocker)  # run is awaiting review
    captured = _capture_resume(mocker)

    async with _client() as c:
        r = await c.post(
            "/runs/edit-test/hitl",
            json={
                "decision": "approved",
                "feedback": "",
                "edited_body": "Custom subject body here",
            },
            headers=REVIEWER,
        )

    assert r.status_code == 200
    assert captured["cmd"].resume == {
        "decision": "approved",
        "feedback": "",
        "edited_body": "Custom subject body here",
    }


@pytest.mark.asyncio
async def test_hitl_empty_edited_body_keeps_original_draft(mocker):
    """Omitting edited_body resumes with an empty string (use the original draft)."""
    _fake_supabase(mocker)
    _mock_redis_pending(mocker)  # run is awaiting review
    captured = _capture_resume(mocker)

    async with _client() as c:
        r = await c.post(
            "/runs/empty-edit/hitl",
            json={"decision": "approved", "feedback": ""},
            headers=REVIEWER,
        )

    assert r.status_code == 200
    assert captured["cmd"].resume["edited_body"] == ""


@pytest.mark.asyncio
async def test_hitl_returns_409_when_run_not_interrupted(mocker):
    """A run with no pending HITL payload cannot be resumed (409, no ainvoke)."""
    _fake_supabase(mocker)
    _mock_redis_pending(mocker, pending=None)  # not awaiting review
    spy = mocker.patch("backend.graph.supervisor.agentiq_graph.ainvoke", AsyncMock())

    async with _client() as c:
        r = await c.post(
            "/runs/not-interrupted/hitl",
            json={"decision": "approved", "feedback": ""},
            headers=REVIEWER,
        )

    assert r.status_code == 409
    assert "not currently awaiting HITL review" in str(r.json())
    spy.assert_not_called()  # the graph was never resumed


@pytest.mark.asyncio
async def test_hitl_second_call_returns_409(mocker):
    """Idempotency: the first resume succeeds; a second submit (pending now
    cleared) returns 409 instead of re-invoking a finished graph."""
    _fake_supabase(mocker)
    # First check sees the pending payload; the second sees None (cleared).
    _mock_redis_pending(
        mocker, pending=[{"draft": {}, "eval_feedback": ""}, None]
    )
    mocker.patch(
        "backend.graph.supervisor.agentiq_graph.ainvoke",
        AsyncMock(
            return_value={
                "token_usage": {},
                "analysis_output": {},
                "draft_output": {},
                "eval_output": {},
                "error": "",
            }
        ),
    )

    async with _client() as c:
        r1 = await c.post(
            "/runs/twice/hitl",
            json={"decision": "approved", "feedback": ""},
            headers=REVIEWER,
        )
        r2 = await c.post(
            "/runs/twice/hitl",
            json={"decision": "approved", "feedback": ""},
            headers=REVIEWER,
        )

    assert r1.status_code == 200
    assert r2.status_code == 409
    assert "not currently awaiting HITL review" in str(r2.json())


@pytest.mark.asyncio
async def test_background_failure_emits_run_error_event(mocker):
    """A pipeline crash emits a distinct run_error event (not a 'complete')."""
    _fake_supabase(mocker)
    mocker.patch(
        "backend.graph.supervisor.run_pipeline",
        AsyncMock(side_effect=Exception("Claude API down")),
    )
    from backend.api.routes import _execute_run
    from backend.db.redis_state import get_redis_state

    run_id = "bg-fail-run"
    await _execute_run(run_id, {"company_name": "Acme"})

    events = await get_redis_state().get_events_since(run_id, 0)
    errors = [e for e in events if e.get("type") == "run_error"]
    assert errors, "expected a run_error event in Redis"
    assert "error" in errors[0]
    assert "Claude API down" in errors[0]["error"]


@pytest.mark.asyncio
async def test_hitl_status_returns_pending_true_when_hitl_active(mocker):
    """When a review window is open, status reports pending=True with timing + payload."""
    from backend.db.redis_state import TTL_SECONDS

    payload = {"draft": {"subject": "s", "body": "b"}, "eval_feedback": "needs work"}
    rs = MagicMock()
    rs.get_hitl_pending = AsyncMock(return_value=payload)
    rs.get_hitl_age_seconds = AsyncMock(return_value=42.0)
    mocker.patch("backend.api.routes.get_redis_state", return_value=rs)

    async with _client() as c:
        r = await c.get("/runs/active-run/hitl/status", headers=REVIEWER)

    assert r.status_code == 200
    body = r.json()
    assert body["pending"] is True
    assert body["age_seconds"] == 42.0
    assert body["expires_in_seconds"] == TTL_SECONDS - 42.0
    assert body["payload"] == payload


@pytest.mark.asyncio
async def test_hitl_status_returns_pending_false_when_no_hitl(mocker):
    """With no pending review, status reports pending=False and null timing/payload."""
    rs = MagicMock()
    rs.get_hitl_pending = AsyncMock(return_value=None)
    rs.get_hitl_age_seconds = AsyncMock(return_value=None)
    mocker.patch("backend.api.routes.get_redis_state", return_value=rs)

    async with _client() as c:
        r = await c.get("/runs/idle-run/hitl/status", headers=REVIEWER)

    assert r.status_code == 200
    body = r.json()
    assert body["pending"] is False
    assert body["age_seconds"] is None
    assert body["expires_in_seconds"] is None
    assert body["payload"] is None
