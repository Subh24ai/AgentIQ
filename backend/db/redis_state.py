"""Redis-backed live run state for SSE streaming and HITL signalling.

Keys (all expire after 24h):
- ``agentiq:run:{run_id}:status``      -> current node name (string)
- ``agentiq:run:{run_id}:events``      -> list of JSON-encoded events
- ``agentiq:run:{run_id}:hitl``        -> JSON HITL interrupt payload (when pending)
- ``agentiq:run:{run_id}:hitl_round``  -> monotonic counter of HITL rounds (INCR)

Every method is resilient: Redis errors are logged and swallowed so that a
transient Redis outage never crashes an agent node or a request handler.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import redis.asyncio as aioredis

from backend.config import get_settings

logger = logging.getLogger("agentiq.redis")

# 7 days — gives reviewers reasonable time to act.
# For production, replace MemorySaver with AsyncPostgresSaver so
# graph state survives server restarts. See supervisor.py TODO.
TTL_SECONDS = 604800


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RedisStateManager:
    """Async wrapper over Redis for per-run live state."""

    def __init__(self, url: Optional[str] = None) -> None:
        self._url = url or get_settings().redis_url
        self._client: Optional[aioredis.Redis] = None

    def _get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(self._url, decode_responses=True)
        return self._client

    @staticmethod
    def _status_key(run_id: str) -> str:
        return f"agentiq:run:{run_id}:status"

    @staticmethod
    def _events_key(run_id: str) -> str:
        return f"agentiq:run:{run_id}:events"

    @staticmethod
    def _hitl_key(run_id: str) -> str:
        return f"agentiq:run:{run_id}:hitl"

    @staticmethod
    def _hitl_round_key(run_id: str) -> str:
        return f"agentiq:run:{run_id}:hitl_round"

    @staticmethod
    def _hitl_set_at_key(run_id: str) -> str:
        return f"agentiq:run:{run_id}:hitl_set_at"

    async def set_node_status(self, run_id: str, node_name: str) -> None:
        try:
            client = self._get_client()
            key = self._status_key(run_id)
            await client.set(key, node_name, ex=TTL_SECONDS)
        except Exception:
            logger.warning("redis set_node_status failed for %s", run_id, exc_info=True)

    async def get_node_status(self, run_id: str) -> Optional[str]:
        try:
            return await self._get_client().get(self._status_key(run_id))
        except Exception:
            logger.warning("redis get_node_status failed for %s", run_id, exc_info=True)
            return None

    async def append_event(self, run_id: str, event_dict: dict[str, Any]) -> None:
        try:
            event = {**event_dict}
            event.setdefault("timestamp", _now_iso())
            client = self._get_client()
            key = self._events_key(run_id)
            await client.rpush(key, json.dumps(event))
            await client.expire(key, TTL_SECONDS)
        except Exception:
            logger.warning("redis append_event failed for %s", run_id, exc_info=True)

    async def get_events_since(self, run_id: str, offset: int) -> list[dict[str, Any]]:
        try:
            raw = await self._get_client().lrange(self._events_key(run_id), offset, -1)
            return [json.loads(item) for item in raw]
        except Exception:
            logger.warning("redis get_events_since failed for %s", run_id, exc_info=True)
            return []

    async def set_hitl_pending(self, run_id: str, payload: dict[str, Any]) -> None:
        try:
            client = self._get_client()
            await client.set(self._hitl_key(run_id), json.dumps(payload), ex=TTL_SECONDS)
            # Record when the review window opened so callers can compute its age
            # (and remaining time) and expire stale reviews. Same 7-day TTL.
            await client.set(self._hitl_set_at_key(run_id), str(time.time()), ex=TTL_SECONDS)
        except Exception:
            logger.warning("redis set_hitl_pending failed for %s", run_id, exc_info=True)

    async def get_hitl_age_seconds(self, run_id: str) -> float | None:
        """Returns seconds since HITL was set, or None if key missing."""

        try:
            raw = await self._get_client().get(self._hitl_set_at_key(run_id))
            return time.time() - float(raw) if raw else None
        except Exception:
            logger.warning("redis get_hitl_age_seconds failed for %s", run_id, exc_info=True)
            return None

    async def get_hitl_pending(self, run_id: str) -> Optional[dict[str, Any]]:
        try:
            raw = await self._get_client().get(self._hitl_key(run_id))
            return json.loads(raw) if raw else None
        except Exception:
            logger.warning("redis get_hitl_pending failed for %s", run_id, exc_info=True)
            return None

    async def clear_hitl(self, run_id: str) -> None:
        try:
            await self._get_client().delete(
                self._hitl_key(run_id), self._hitl_set_at_key(run_id)
            )
        except Exception:
            logger.warning("redis clear_hitl failed for %s", run_id, exc_info=True)

    async def increment_hitl_round(self, run_id: str) -> int:
        """Atomically bump the HITL round counter and (re)apply its 24h TTL.

        Returns the new round number (0 on a Redis failure). The counter is the
        signal the SSE generator uses to detect a *new* interrupt in the
        revision loop, not just the first one.
        """

        try:
            client = self._get_client()
            key = self._hitl_round_key(run_id)
            value = await client.incr(key)
            await client.expire(key, TTL_SECONDS)
            return int(value)
        except Exception:
            logger.warning("redis increment_hitl_round failed for %s", run_id, exc_info=True)
            return 0

    async def get_hitl_round(self, run_id: str) -> int:
        """Return the current HITL round counter (0 if never set)."""

        try:
            raw = await self._get_client().get(self._hitl_round_key(run_id))
            return int(raw) if raw else 0
        except Exception:
            logger.warning("redis get_hitl_round failed for %s", run_id, exc_info=True)
            return 0


_manager: Optional[RedisStateManager] = None


def get_redis_state() -> RedisStateManager:
    """Return the process-wide RedisStateManager singleton."""

    global _manager
    if _manager is None:
        _manager = RedisStateManager()
    return _manager
