"""Shared pytest fixtures and path setup for the AgentIQ test suite."""

import os
import sys

import pytest

# Ensure the project root is importable as `backend.*` regardless of CWD.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Deterministic, credential-free env for tests.
os.environ.setdefault("ANTHROPIC_API_KEY", "test_key")
os.environ.setdefault("TAVILY_API_KEY", "test_key")
os.environ.setdefault("SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_ANON_KEY", "test_anon_key")
os.environ.setdefault("JWT_SECRET", "test_secret_at_least_32_characters_long!!")
os.environ.setdefault("USE_MOCK_GMAIL", "true")


@pytest.fixture
def sample_lead() -> dict:
    return {
        "company_name": "Acme Corp",
        "website": "https://example.com",
        "icp_notes": "B2B SaaS, 50-200 employees, eng-led",
    }
