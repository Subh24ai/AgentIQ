"""Application configuration loaded from environment / .env via pydantic-settings."""

from __future__ import annotations

import time
from collections import OrderedDict
from functools import lru_cache
from typing import Callable, ClassVar

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings for AgentIQ, populated from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # The placeholder secret shipped in .env.example. The server refuses to
    # start with this value (outside APP_ENV=test).
    DEFAULT_SECRET: ClassVar[str] = "changeme_min32chars_replace_this"

    # --- LLM / tooling ---
    anthropic_api_key: str = ""
    tavily_api_key: str = ""

    # --- Supabase ---
    supabase_url: str = ""
    supabase_anon_key: str = ""

    # --- Observability ---
    langsmith_api_key: str = ""
    langsmith_project: str = "agentiq"

    # --- Infra ---
    redis_url: str = "redis://localhost:6379"
    jwt_secret: str = DEFAULT_SECRET

    # --- Behaviour toggles ---
    use_mock_gmail: bool = True

    # --- Cost controls ---
    cost_limit_usd: float = 0.50
    default_model: str = "claude-sonnet-4-6"

    @model_validator(mode="after")
    def validate_jwt_secret(self) -> "Settings":
        """Refuse to start with the placeholder JWT secret outside tests."""

        import os

        env = os.getenv("APP_ENV", "development")
        if self.jwt_secret == self.DEFAULT_SECRET and env != "test":
            raise ValueError(
                "JWT_SECRET must be changed from the default value. "
                "Set a strong random secret in your .env file. "
                'Generate one with: python3 -c "import secrets; '
                'print(secrets.token_hex(32))"'
            )
        return self

    @property
    def cost_per_1k_tokens(self) -> dict[str, dict[str, float]]:
        """USD cost per 1K tokens, keyed by model then input/output."""

        return {
            "claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
        }


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings singleton."""

    return Settings()


# Module-level convenience handle.
settings = get_settings()


CACHE_WINDOW_SECONDS = 5 * 60  # prompt caching is worthwhile within a 5-min window


class CostOptimizer:
    """Tracks token usage and decides when prompt caching is worthwhile.

    - ``should_use_cache`` returns True when the same prompt hash was seen within
      the last 5 minutes (recent + identical => the drafter should send the
      Anthropic cache_control header).
    - ``estimate_cost`` prices a call from the config cost table.
    - ``log_usage`` records per-node usage and keeps a running total.
    """

    def __init__(self, max_entries: int = 512, clock: Callable[[], float] = time.time) -> None:
        self._max_entries = max_entries
        self._clock = clock
        self._seen: "OrderedDict[str, float]" = OrderedDict()
        self._usage_log: list[dict] = []
        self.running_total_usd: float = 0.0

    def should_use_cache(self, prompt_hash: str) -> bool:
        now = self._clock()
        previous = self._seen.get(prompt_hash)
        recent = previous is not None and (now - previous) <= CACHE_WINDOW_SECONDS

        # Record/refresh this prompt as most-recently-seen (LRU).
        self._seen[prompt_hash] = now
        self._seen.move_to_end(prompt_hash)
        while len(self._seen) > self._max_entries:
            self._seen.popitem(last=False)

        return recent

    def estimate_cost(
        self, input_tokens: int, output_tokens: int, model: str, cache_read_tokens: int = 0
    ) -> float:
        rates = get_settings().cost_per_1k_tokens.get(model, {})
        cost = (input_tokens / 1000.0) * rates.get("input", 0.0) + (
            output_tokens / 1000.0
        ) * rates.get("output", 0.0)
        # Cache reads are charged at 10% of the input price.
        cost += (cache_read_tokens / 1000.0) * rates.get("input", 0.0) * 0.1
        return round(cost, 6)

    def log_usage(self, run_id: str, node: str, usage: dict) -> float:
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        cache_read_tokens = int(usage.get("cache_read_tokens", 0) or 0)
        model = usage.get("model", get_settings().default_model)
        cost = usage.get("cost_usd")
        if cost is None:
            cost = self.estimate_cost(input_tokens, output_tokens, model, cache_read_tokens)
        self._usage_log.append(
            {
                "run_id": run_id,
                "node": node,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": cache_read_tokens,
                "cost_usd": cost,
            }
        )
        self.running_total_usd = round(self.running_total_usd + cost, 6)
        return self.running_total_usd
