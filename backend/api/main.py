"""AgentIQ FastAPI application entrypoint.

Phase 2: security headers, in-memory rate limiting, structured request logging,
JWT auth router, and locked-down CORS.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.middleware import (
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
)
from backend.api.routes import router as runs_router
from backend.config import get_settings
from backend.security.auth import router as auth_router

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("agentiq")

VERSION = "0.1.0"
ALLOWED_ORIGINS = ["http://localhost:5173"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()  # surface misconfiguration early
    logger.info(json.dumps({"event": "startup", "version": VERSION}))
    yield


app = FastAPI(title="AgentIQ", version=VERSION, lifespan=lifespan)

# Middleware. Note: the LAST added middleware is the OUTERMOST. We add the rate
# limiter innermost (so security headers wrap even its 429 responses), then
# security headers, then request logging, then CORS as the outermost layer.
app.add_middleware(RateLimitMiddleware, max_requests=60, window_seconds=60)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(runs_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": VERSION}
