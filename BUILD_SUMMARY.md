# AgentIQ — Build Summary (All Phases)

Autonomous multi-agent B2B outreach platform. LangGraph supervisor orchestrates
4 Claude agents (Researcher → Analyst → Drafter → Evaluator) with HITL review,
SSE streaming, prompt-injection firewall, LLM-as-judge eval, and a cost guard.

**Final status:** 6/6 phases complete · **46/46 tests passing** · Python 3.11 · React 19.

---

## Project structure

```
AgentIQ/
├── backend/
│   ├── __init__.py
│   ├── config.py                     # Settings (pydantic-settings) + CostOptimizer
│   ├── Dockerfile                    # backend image (build context = repo root)
│   ├── agents/
│   │   ├── _common.py                # model build, structured-output, token accounting, emit_node_event
│   │   ├── researcher.py             # 3x Tavily + scrape → ResearchOutput
│   │   ├── analyst.py                # ICP fit (clamped 0–1) → AnalysisOutput
│   │   ├── drafter.py                # ≤200-word email + prompt caching → DraftOutput
│   │   └── evaluator.py              # adversarial judge (pass ≥0.75) → EvalOutput
│   ├── graph/
│   │   ├── state.py                  # AgentIQState TypedDict + new_state()
│   │   └── supervisor.py             # StateGraph, routing, cost_guard, hitl interrupt(), run_pipeline()
│   ├── api/
│   │   ├── main.py                   # FastAPI app, middleware, routers, CORS
│   │   ├── middleware.py             # security headers, rate limit, JSON request logs
│   │   └── routes.py                 # POST /runs, SSE /stream, POST /hitl, GET /runs[/{id}]
│   ├── security/
│   │   ├── injection_guard.py        # PromptInjectionGuard (17 patterns) → ScanResult
│   │   └── auth.py                   # JWT HS256, /auth/token, verify_token, require_role
│   ├── tools/
│   │   ├── search.py                 # TavilySearchTool + PlaywrightScraper (firewalled)
│   │   └── gmail_mcp.py              # GmailMCPClient + MockGmailClient
│   ├── db/
│   │   ├── supabase_client.py        # async singleton + Pydantic write/read models
│   │   ├── redis_state.py            # RedisStateManager (resilient) for live state/SSE
│   │   └── migrations/001_initial.sql
│   └── eval/
│       └── judge.py                  # AgentIQEvaluator — native Claude-as-judge eval
├── frontend/
│   ├── Dockerfile                    # two-stage node→nginx
│   ├── nginx.conf                    # SPA routing + /api proxy (SSE-safe)
│   ├── vite.config.ts                # /api proxy → :8000 (prefix stripped)
│   ├── index.html
│   └── src/
│       ├── main.tsx, App.tsx         # router + protected routes
│       ├── types.ts, store.ts        # TS models + Zustand store
│       ├── api.ts, auth.ts           # API client + sessionStorage JWT
│       ├── index.css                 # single dark-theme stylesheet
│       ├── pages/                    # LoginPage, DashboardPage, RunPage
│       └── components/               # AgentStep, EventFeed, HITLPanel, CostBadge
├── tests/                            # 46 tests (all external calls mocked)
│   ├── conftest.py, eval_fixtures.py
│   ├── test_state.py(5) test_security.py(8) test_agents.py(10)
│   ├── test_graph.py(5) test_routes.py(8) test_eval.py(6) test_cost.py(4)
├── .github/workflows/ci.yml          # GitHub Actions (py3.11 + redis service)
├── docker-compose.yml                # redis + backend(:8000) + frontend(:3000)
├── requirements.txt                  # 19 pinned deps
├── pytest.ini, .gitignore, .env.example, README.md
```

---

## Phase 1 — Scaffold + typed state + Supabase schema
- Full `backend/` package tree, `tests/`, empty `frontend/`.
- `requirements.txt` — 19 exact pins (all installed on Python 3.11).
- `backend/graph/state.py` — `AgentIQState` TypedDict with `messages: Annotated[list, operator.add]`; `new_state()` defaults `hitl_decision="pending"`.
- `backend/config.py` — `Settings` (pydantic-settings) + `cost_per_1k_tokens` property.
- `backend/db/migrations/001_initial.sql` — `runs`, `outreach_log`, `hitl_reviews`, `eval_results` + FK indexes.
- `backend/db/supabase_client.py` — lazy async singleton, Pydantic-validated methods.
- `backend/api/main.py` — `/health`.
- `docker-compose.yml`, `.env.example`, `.gitignore`, `pytest.ini`, `conftest.py`, `README.md`.
- **Tests: `tests/test_state.py` → 5 passed.**

## Phase 2 — Security: injection firewall + JWT + middleware
- `backend/security/injection_guard.py` — `PromptInjectionGuard`, 17 regex patterns (role-switch, prompt-leak, exfiltration, jailbreak, indirect markers); `scan()` → `ScanResult(is_safe, matched_patterns, risk_score)`, never raises.
- `backend/security/auth.py` — JWT HS256 24h, `/auth/token`, `verify_token` dep, in-memory users (admin/reviewer), bonus `require_role()`.
- `backend/api/middleware.py` — `SecurityHeadersMiddleware` (4 headers), `RateLimitMiddleware` (60/60s/IP, 429 + Retry-After), `RequestLoggingMiddleware` (JSON to stdout).
- `backend/api/main.py` — wired middleware, auth router, CORS (localhost:5173), startup JSON log.
- **Tests: `tests/test_security.py` → 8 passed.** Live: headers + rate limit + auth verified.

## Phase 3 — Four agents + LangGraph supervisor + HITL
- `backend/tools/search.py` — `TavilySearchTool`, `PlaywrightScraper` (httpx, 10s, firewalled → BLOCKED_CONTENT).
- `backend/agents/_common.py` — `get_chat_model`, `run_structured` (`with_structured_output(..., include_raw=True)`), `accumulate_usage`.
- `researcher.py` (3 parallel Tavily + scrape + backoff), `analyst.py` (clamped fit_score), `drafter.py` (≤200-word body, prompt caching via `default_headers`), `evaluator.py` (adversarial judge, `passed` derived ≥0.75, logs to Supabase).
- `backend/graph/supervisor.py` — `StateGraph` (6 nodes), conditional routing, `cost_guard`, `hitl` via `interrupt()`, `MemorySaver`, `agentiq_graph`, `run_pipeline()`.
- `backend/tools/gmail_mcp.py` — real + mock Gmail clients.
- **Tests: `tests/test_agents.py`(10) + `tests/test_graph.py`(5) → 15 passed.** HITL interrupt/resume verified.

## Phase 4 — FastAPI routes + SSE + HITL resume + Redis
- `backend/db/redis_state.py` — `RedisStateManager` (resilient): `set_node_status`, `append_event`, `get_events_since`, `set/get/clear_hitl`; 24h TTL.
- `backend/api/routes.py` — `POST /runs` (background pipeline), `GET /runs/{id}/stream` (SSE: update/hitl_required/complete; token via `?token=`), `POST /runs/{id}/hitl` (reviewer-only, `Command(resume=...)` + `_publish_terminal`), `GET /runs/{id}` (404), `GET /runs` (paginated).
- Agents emit live events at start/end via `emit_node_event`.
- **Tests: `tests/test_routes.py` → 8 passed.** Live: POST /runs → run_id, no-auth → 401.

## Phase 5 — React frontend (Vite + TS, no UI lib)
- `types.ts`, `store.ts` (Zustand), `api.ts` (incl. EventSource SSE), `auth.ts` (sessionStorage).
- `App.tsx` (router + protected), pages `LoginPage`/`DashboardPage`/`RunPage`, components `AgentStep`/`EventFeed`/`HITLPanel`/`CostBadge`.
- `index.css` single dark theme (#0f1117, amber #f0a500, monospace feed).
- `vite.config.ts` `/api` proxy. Backend: added `_publish_terminal()` so HITL resume reaches completion on the stream.
- **`npm run build` → 0 TS errors; dev server boots.**

## Phase 6 — Eval framework + cost optimizer + CI + Docker + README
- `backend/eval/judge.py` — `AgentIQEvaluator.run_eval_suite` (`EvalCase`/`NativeEvalMetrics`/`EvalCaseResult`/`EvalSuiteResult`), native Claude-as-judge faithfulness + answer-relevancy, blocks injection/empty drafts.
- `tests/eval_fixtures.py` — high-fit / low-fit / injection cases.
- `backend/config.py` — `CostOptimizer` (`should_use_cache` 5-min LRU, `estimate_cost`, `log_usage`).
- `.github/workflows/ci.yml`, `backend/Dockerfile`, `frontend/Dockerfile`, `frontend/nginx.conf`, frontend service in compose, full `README.md`.
- **Tests: `tests/test_eval.py`(6) + `tests/test_cost.py`(4) → 10 passed. Suite total: 46 passed.**

---

## Key deviations from the guide (all forced by real facts)
1. **Python 3.11** (system 3.9 too old). Run uvicorn/pytest **from project root**; imports are `backend.*`. Correct server cmd: `uvicorn backend.api.main:app` (NOT `cd backend && uvicorn api.main:app`).
2. **React 19** (Vite's current scaffold default), not 18 — code is compatible.
3. **`default_headers`** for the prompt-caching beta header (langchain-anthropic has no `extra_headers`). `usage_metadata` keys are `input_tokens`/`output_tokens`.
4. **RAGAS removed, replaced with native Claude-as-judge** — `ragas 0.4.3` can't import with `langchain-community 0.4.2` (removed vertexai submodule). `backend/eval/judge.py` implements equivalent faithfulness + answer-relevancy metrics directly. `ragas` dropped from requirements.
5. **`pytest-cov`** installed in CI only (not in requirements.txt).
6. **Your Docker stack occupies ports 8000/5173/6379** — local smoke tests used alt ports (e.g. 8002).
7. **`docs/architecture.png`** is referenced in README but not generated.

## Run commands
```bash
# Setup
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in API keys

# Tests (46)
pytest --tb=short -v

# Backend (from project ROOT)
uvicorn backend.api.main:app --reload

# Frontend
cd frontend && npm install && npm run dev   # :5173

# Everything via Docker
docker compose up --build     # redis + backend(:8000) + frontend(:3000)
```
Dev users: `admin` / `agentiq_admin`, `reviewer` / `agentiq_review`.
```
```
