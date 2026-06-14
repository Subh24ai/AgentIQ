"""Shared helpers for AgentIQ agent nodes.

Centralises model construction, structured-output calls, and token/cost
accounting so every agent updates ``state["token_usage"]`` consistently.
"""

from __future__ import annotations

from typing import Any, Optional, Type, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from backend.config import get_settings
from backend.db.redis_state import get_redis_state

T = TypeVar("T", bound=BaseModel)


PROMPT_CACHING_HEADER = {"anthropic-beta": "prompt-caching-2024-07-31"}


def cached_system(text: str) -> list[dict]:
    """Build a system-message content block marked for Anthropic prompt caching.

    The beta header (see :data:`PROMPT_CACHING_HEADER`) enables the feature; the
    ``cache_control`` block tells Anthropic *which* prefix to cache so a long,
    stable system prompt is cached on first use and reused (~90% token savings).
    """

    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def get_chat_model(
    model: Optional[str] = None,
    default_headers: Optional[dict[str, str]] = None,
    temperature: float = 0.3,
):
    """Construct a ChatAnthropic client.

    ``default_headers`` is how the Anthropic beta header (e.g. prompt caching)
    is injected on the langchain-anthropic client — the langchain field is
    ``default_headers`` (the raw Anthropic SDK kwarg is ``extra_headers``).
    Imported lazily so tests that mock the agents never need the package.
    """

    from langchain_anthropic import ChatAnthropic

    settings = get_settings()
    kwargs: dict[str, Any] = {
        "model": model or settings.default_model,
        "temperature": temperature,
        "anthropic_api_key": settings.anthropic_api_key,
    }
    if default_headers:
        kwargs["default_headers"] = default_headers
    return ChatAnthropic(**kwargs)


def is_over_budget(state: dict) -> bool:
    """True when cumulative cost has exceeded the configured per-run limit."""

    cost = (state.get("token_usage") or {}).get("cost_usd", 0.0)
    return cost > get_settings().cost_limit_usd


def accumulate_usage(
    state: dict, usage_metadata: Optional[dict], response: Any = None
) -> None:
    """Fold a response's ``usage_metadata`` into cumulative ``state['token_usage']``.

    Uses the real ``UsageMetadata`` keys (``input_tokens``/``output_tokens``/
    ``total_tokens`` and nested ``input_token_details`` for cache hits) — these
    are the keys langchain-anthropic actually returns. Cache reads are billed at
    ~10% of the input rate. Pricing uses the *actual* model from the response
    metadata when available, falling back to the configured default.
    """

    if not usage_metadata:
        return
    settings = get_settings()
    input_tok = int(usage_metadata.get("input_tokens", 0) or 0)
    output_tok = int(usage_metadata.get("output_tokens", 0) or 0)
    details = usage_metadata.get("input_token_details") or {}
    cache_read = int(details.get("cache_read", 0) or 0)
    cache_creation = int(details.get("cache_creation", 0) or 0)

    # Read the actual model from response metadata, falling back to default.
    actual_model = settings.default_model
    if response is not None:
        meta = getattr(response, "response_metadata", None) or {}
        actual_model = meta.get("model") or settings.default_model
    # Normalize version suffixes, e.g. "claude-sonnet-4-6-20251001" ->
    # "claude-sonnet-4-6", so the rate table matches.
    for known_model in settings.cost_per_1k_tokens:
        if actual_model.startswith(known_model):
            actual_model = known_model
            break

    rates = settings.cost_per_1k_tokens.get(actual_model, {})
    cost = (input_tok / 1000.0) * rates.get("input", 0.0) + (
        output_tok / 1000.0
    ) * rates.get("output", 0.0)
    # Cache reads are charged at 10% of the input price.
    cost += (cache_read / 1000.0) * rates.get("input", 0.0) * 0.1

    usage = state.get("token_usage") or {}
    usage["input_tokens"] = usage.get("input_tokens", 0) + input_tok
    usage["output_tokens"] = usage.get("output_tokens", 0) + output_tok
    usage["cache_read_tokens"] = usage.get("cache_read_tokens", 0) + cache_read
    usage["cache_creation_tokens"] = usage.get("cache_creation_tokens", 0) + cache_creation
    usage["total_tokens"] = usage.get("total_tokens", 0) + input_tok + output_tok
    usage["cost_usd"] = round(usage.get("cost_usd", 0.0) + cost, 6)
    state["token_usage"] = usage


async def emit_node_event(
    state: dict, node: str, status: str, partial_output: Optional[dict] = None
) -> None:
    """Publish a live event to Redis for the SSE stream (resilient; never raises).

    Called at the start ("active") and end ("complete") of each agent node.
    """

    rs = get_redis_state()
    run_id = state.get("run_id", "")
    await rs.set_node_status(run_id, node)
    await rs.append_event(
        run_id,
        {
            "node": node,
            "status": status,
            "partial_output": partial_output or {},
            "token_usage": state.get("token_usage", {}),
        },
    )


async def run_structured(
    model,
    schema: Type[T],
    system: "str | list[dict]",
    human: str,
    state: dict,
) -> T:
    """Call the model for structured output and accumulate token usage.

    Uses ``include_raw=True`` so the raw AIMessage (and its usage_metadata) is
    available for cost accounting even though we return the parsed model.
    """

    chain = model.with_structured_output(schema, include_raw=True)
    result = await chain.ainvoke(
        [SystemMessage(content=system), HumanMessage(content=human)]
    )
    raw = result.get("raw")
    if raw is not None:
        accumulate_usage(state, getattr(raw, "usage_metadata", None), response=raw)
    parsed = result.get("parsed")
    if parsed is None:
        raise ValueError("structured output returned no parsed result")
    return parsed
