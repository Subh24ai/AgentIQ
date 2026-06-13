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


def accumulate_usage(state: dict, usage_metadata: Optional[dict]) -> None:
    """Fold a response's usage_metadata into cumulative ``state['token_usage']``.

    langchain usage_metadata uses ``input_tokens``/``output_tokens``; we map
    those to ``prompt_tokens``/``completion_tokens`` and add the USD cost.
    """

    if not usage_metadata:
        return
    settings = get_settings()
    prompt = int(usage_metadata.get("input_tokens", 0) or 0)
    completion = int(usage_metadata.get("output_tokens", 0) or 0)

    rates = settings.cost_per_1k_tokens.get(settings.default_model, {})
    cost = (prompt / 1000.0) * rates.get("input", 0.0) + (
        completion / 1000.0
    ) * rates.get("output", 0.0)

    usage = state.get("token_usage") or {}
    usage["prompt_tokens"] = usage.get("prompt_tokens", 0) + prompt
    usage["completion_tokens"] = usage.get("completion_tokens", 0) + completion
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
    system: str,
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
        accumulate_usage(state, getattr(raw, "usage_metadata", None))
    parsed = result.get("parsed")
    if parsed is None:
        raise ValueError("structured output returned no parsed result")
    return parsed
