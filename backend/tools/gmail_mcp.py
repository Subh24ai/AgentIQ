"""Gmail sending tools.

Two implementations selected via config (``USE_MOCK_GMAIL``):
- :class:`GmailMCPClient` — talks to the Gmail MCP server. Requires Gmail MCP to
  be connected in the Claude environment (manual OAuth setup).
- :class:`MockGmailClient` — logs to stdout and appends to ./sent_emails.jsonl.

PRODUCTION NOTE: replace the mock with a proper OAuth 2.1 credential flow.
Never hardcode OAuth tokens.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

from backend.config import get_settings

logger = logging.getLogger("agentiq.gmail")

GMAIL_MCP_URL = "https://gmailmcp.googleapis.com/mcp/v1"
SENT_LOG = Path("sent_emails.jsonl")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GmailMCPClient:
    """Client for the Gmail MCP server (requires connected Gmail MCP / OAuth)."""

    def __init__(self, base_url: str = GMAIL_MCP_URL) -> None:
        self._base_url = base_url

    async def send_email(self, to: str, subject: str, body: str) -> dict:
        payload = {"to": to, "subject": subject, "body": body}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{self._base_url}/messages/send", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return {
            "message_id": data.get("id", ""),
            "thread_id": data.get("threadId", ""),
            "sent_at": _now_iso(),
        }


class MockGmailClient:
    """Local mock: logs the email and appends it to sent_emails.jsonl."""

    async def send_email(self, to: str, subject: str, body: str) -> dict:
        record = {
            "message_id": f"mock-{uuid.uuid4()}",
            "thread_id": f"mock-thread-{uuid.uuid4()}",
            "sent_at": _now_iso(),
            "to": to,
            "subject": subject,
            "body": body,
        }
        logger.info("MOCK GMAIL send to=%s subject=%s", to, subject)
        with SENT_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        return {
            "message_id": record["message_id"],
            "thread_id": record["thread_id"],
            "sent_at": record["sent_at"],
        }


def get_gmail_client():
    """Return the mock or real client based on ``USE_MOCK_GMAIL``."""

    if get_settings().use_mock_gmail:
        return MockGmailClient()
    return GmailMCPClient()
