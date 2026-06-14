"""Researcher agent: gathers external intelligence on the target company."""

from __future__ import annotations

import asyncio
import json
import logging

from pydantic import BaseModel, Field

from backend.agents._common import (
    emit_node_event,
    get_chat_model,
    is_over_budget,
    run_structured,
)
from backend.config import get_settings
from backend.security.injection_guard import PromptInjectionGuard
from backend.tools.search import TavilySearchTool, PlaywrightScraper

logger = logging.getLogger("agentiq.researcher")

_SYSTEM = (
    "You are a B2B sales researcher. Synthesize the provided search results and "
    "website text into a concise, factual company profile. Do not invent facts; "
    "if something is unknown, say so."
)


class ResearchOutput(BaseModel):
    company_summary: str
    tech_stack: list[str] = Field(default_factory=list)
    recent_news: list[str] = Field(default_factory=list)
    funding_status: str = ""
    employee_count_estimate: str = ""
    pain_points: list[str] = Field(default_factory=list)


async def researcher_node(state: dict) -> dict:
    try:
        if is_over_budget(state):
            state["error"] = f"Cost limit ${get_settings().cost_limit_usd} exceeded"
            return state
        await emit_node_event(state, "researcher", "active")
        lead = state.get("lead", {})
        company = lead.get("company_name", "")
        website = lead.get("website", "")

        queries = [
            f"{company} company overview funding",
            f"{company} recent news 2025 2026",
            f"{company} tech stack engineering blog",
        ]
        tool = TavilySearchTool()

        # Run all queries in parallel and tolerate per-query failures: one bad
        # query must not sink the whole research step. Failed queries contribute
        # no results; we proceed with whatever came back.
        raw_results = await asyncio.gather(
            *(tool.search(q) for q in queries), return_exceptions=True
        )
        results: list[list[dict]] = []
        failures = 0
        for i, r in enumerate(raw_results):
            if isinstance(r, Exception):
                failures += 1
                logger.warning(
                    json.dumps(
                        {
                            "event": "tavily_partial_failure",
                            "query_index": i,
                            "query": queries[i],
                            "error": str(r),
                        }
                    )
                )
                results.append([])  # empty result for failed query
            else:
                results.append(r)
        all_results = [item for sublist in results for item in sublist]

        # Only a hard failure if EVERY query raised. A successful-but-empty
        # search (no hits) is not a failure — proceed with what we have.
        if failures == len(queries):
            state["error"] = "researcher failed: all search queries failed"
            return state

        # Scrape is best-effort. The scraper already firewalls site text (returns
        # BLOCKED_CONTENT on a hit, see tools/search.py); a scrape failure here is
        # non-fatal — log it and continue without site text.
        try:
            scraper = PlaywrightScraper()
            site_text = await scraper.scrape(website) if website else ""
        except Exception as exc:
            logger.warning("scraper failed, continuing without site text: %s", exc)
            site_text = ""

        # OWASP LLM01/02: Tavily results are external/untrusted. Scan each result
        # and redact (rather than drop) any content carrying injection signatures
        # before it is joined into the LLM prompt.
        guard = PromptInjectionGuard()
        safe_results = []
        for r in all_results:
            content = r.get("content", "")
            scan = guard.scan(content)
            if scan.is_safe:
                safe_results.append(r)
            else:
                logger.warning(
                    "redacting injected tavily content from %s: patterns=%s",
                    r.get("url", ""),
                    scan.matched_patterns,
                )
                safe_results.append(
                    {**r, "content": "[CONTENT REDACTED: injection pattern detected]"}
                )

        context = "\n\n".join(
            f"- {r['title']} ({r['url']}): {r['content']}" for r in safe_results
        )
        human = (
            f"Company: {company}\nWebsite: {website}\n\n"
            f"Search results:\n{context}\n\n"
            f"Website text (truncated):\n{site_text[:4000]}"
        )

        model = get_chat_model()
        research = await run_structured(model, ResearchOutput, _SYSTEM, human, state)
        state["research_output"] = research.model_dump()
        await emit_node_event(state, "researcher", "complete", state["research_output"])
    except Exception as exc:
        logger.exception("researcher_node failed")
        state["error"] = f"researcher failed: {exc}"
    return state
