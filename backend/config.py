"""Application configuration loaded from environment / .env via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from typing import ClassVar

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Max number of HITL reject→re-draft cycles before a run is force-terminated.
MAX_HITL_REVISIONS: int = 3


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
    # LangSmith tracing not wired. To enable: pip install langsmith,
    # set LANGCHAIN_TRACING_V2=true + LANGCHAIN_API_KEY in .env,
    # then import langsmith in supervisor.py.

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
                "JWT_SECRET must be at least 32 characters.\n"
                'Generate one with: python3 -c "import secrets; print(secrets.token_hex(32))"\n'
                "Then add it to your .env file."
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
