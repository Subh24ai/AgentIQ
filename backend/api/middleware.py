"""Security & observability middleware for AgentIQ.

- :class:`SecurityHeadersMiddleware` — hardening response headers.
- :class:`RateLimitMiddleware` — in-memory sliding-window limiter (60 req / 60s
  per client IP). NOTE: in-memory state resets on restart and is not shared
  across workers; replace with a Redis-backed limiter for production.
- :class:`RequestLoggingMiddleware` — structured JSON access logs to stdout.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

access_logger = logging.getLogger("agentiq.access")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter: ``max_requests`` per ``window_seconds`` per IP."""

    def __init__(self, app, max_requests: int = 60, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _client_ip(self, request: Request) -> str:
        if request.client and request.client.host:
            return request.client.host
        return "unknown"

    async def dispatch(self, request: Request, call_next) -> Response:
        ip = self._client_ip(request)
        now = time.monotonic()
        window_start = now - self.window_seconds
        hits = self._hits[ip]

        # Drop timestamps outside the current window.
        while hits and hits[0] < window_start:
            hits.popleft()

        if len(hits) >= self.max_requests:
            retry_after = int(self.window_seconds - (now - hits[0])) + 1
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(max(retry_after, 1))},
            )

        hits.append(now)
        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        client_ip = request.client.host if request.client else "unknown"
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            access_logger.info(
                json.dumps(
                    {
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": locals().get("status_code", 500),
                        "latency_ms": latency_ms,
                        "client_ip": client_ip,
                    }
                )
            )
