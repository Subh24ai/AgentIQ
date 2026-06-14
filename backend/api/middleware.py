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
from collections import OrderedDict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

access_logger = logging.getLogger("agentiq.access")

# Cap on the number of distinct client IPs tracked at once, to bound memory.
MAX_TRACKED_IPS = 10_000

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
    """Sliding-window rate limiter: ``max_requests`` per ``window_seconds`` per IP.

    NOTE: This is a single-process in-memory rate limiter. It resets on restart
    and is not shared across multiple workers. For production with multiple
    uvicorn workers, use Redis-backed rate limiting (e.g. slowapi with a redis
    backend).

    The per-IP table is an LRU-bounded ``OrderedDict`` capped at
    ``max_tracked_ips`` so a flood of unique IPs cannot grow it without bound.
    """

    def __init__(
        self,
        app,
        max_requests: int = 60,
        window_seconds: int = 60,
        max_tracked_ips: int = MAX_TRACKED_IPS,
    ) -> None:
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_tracked_ips = max_tracked_ips
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()

    def _client_ip(self, request: Request) -> str:
        if request.client and request.client.host:
            return request.client.host
        return "unknown"

    def _check(self, ip: str) -> bool:
        """Record a request from ``ip``; return False if it exceeds the limit.

        Evicts the least-recently-used IP when the table is at capacity, trims
        timestamps outside the window, and marks ``ip`` most-recently-used.
        """

        now = time.monotonic()
        if ip not in self._hits:
            if len(self._hits) >= self.max_tracked_ips:
                self._hits.popitem(last=False)  # evict oldest (LRU) IP
            self._hits[ip] = deque()
        window = self._hits[ip]

        # Drop timestamps outside the current window.
        while window and window[0] < now - self.window_seconds:
            window.popleft()

        if len(window) >= self.max_requests:
            return False  # rate limit exceeded

        window.append(now)
        self._hits.move_to_end(ip)  # mark as recently used (LRU)
        return True

    async def dispatch(self, request: Request, call_next) -> Response:
        ip = self._client_ip(request)
        if not self._check(ip):
            now = time.monotonic()
            window = self._hits[ip]
            retry_after = int(self.window_seconds - (now - window[0])) + 1 if window else self.window_seconds
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": str(max(retry_after, 1))},
            )
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
