"""Researcher agent: gathers external intelligence on the target company."""

from __future__ import annotations

import asyncio
import logging

from pydantic import BaseModel, Field

from backend.agents._common import emit_node_event, get_chat_model, run_structured
from backend.tools.search import TavilySearchTool, PlaywrightScraper

logger = logging.getLogger("agentiq.researcher")

_MAX_RETRIES = 3

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


async def _search_with_backoff(tool: TavilySearchTool, queries: list[str]) -> list[list[dict]]:
    """Run all queries in parallel with exponential backoff on failure."""

    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            return await asyncio.gather(*(tool.search(q) for q in queries))
        except Exception as exc:  # Tavily API / network errors
            last_exc = exc
            wait = 2 ** attempt
            logger.warning("tavily search failed (attempt %d), backing off %ds: %s",
                           attempt + 1, wait, exc)
            await asyncio.sleep(wait)
    raise last_exc if last_exc else RuntimeError("search failed")


async def researcher_node(state: dict) -> dict:
    try:
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
        search_results = await _search_with_backoff(tool, queries)

        scraper = PlaywrightScraper()
        site_text = await scraper.scrape(website) if website else ""

        flat = [item for group in search_results for item in group]
        context = "\n\n".join(
            f"- {r['title']} ({r['url']}): {r['content']}" for r in flat
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
