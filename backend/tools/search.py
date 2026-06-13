"""Search and scraping tools for the Researcher agent.

- :class:`TavilySearchTool` — thin async wrapper over tavily-python.
- :class:`PlaywrightScraper` — despite the name, uses httpx (Playwright is too
  heavy for CI); fetches page text, strips HTML, and runs the result through the
  prompt-injection firewall before returning it (OWASP LLM02 / indirect injection).
"""

from __future__ import annotations

import re

import httpx

from backend.config import get_settings
from backend.security.injection_guard import PromptInjectionGuard

BLOCKED_CONTENT = "[CONTENT BLOCKED: injection risk detected]"

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


class TavilySearchTool:
    """Async Tavily search returning a normalized list of result dicts."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or get_settings().tavily_api_key

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        from tavily import AsyncTavilyClient

        client = AsyncTavilyClient(api_key=self._api_key)
        resp = await client.search(query, max_results=max_results)
        results = resp.get("results", []) if isinstance(resp, dict) else []
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
                "score": r.get("score", 0.0),
            }
            for r in results
        ]


class PlaywrightScraper:
    """Fetch page text via httpx and firewall it before returning."""

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout
        self._guard = PromptInjectionGuard()

    async def _fetch(self, url: str) -> str:
        async with httpx.AsyncClient(
            timeout=self._timeout, follow_redirects=True
        ) as client:
            resp = await client.get(url, headers={"User-Agent": _USER_AGENT})
            resp.raise_for_status()
            return resp.text

    @staticmethod
    def _strip_html(html: str) -> str:
        text = _TAG_RE.sub(" ", html)
        return _WS_RE.sub(" ", text).strip()

    async def scrape(self, url: str) -> str:
        try:
            html = await self._fetch(url)
        except Exception as exc:  # network/HTTP errors are non-fatal for research
            return f"[SCRAPE FAILED: {exc.__class__.__name__}]"
        text = self._strip_html(html)
        # OWASP LLM02: never let externally-fetched content into the pipeline
        # if it contains injection signatures.
        if not self._guard.scan(text).is_safe:
            return BLOCKED_CONTENT
        return text
