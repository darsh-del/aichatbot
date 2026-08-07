"""Redis cache for read-only MCP catalog results, shared across all users.

One session's `search_activities_by_destination_and_tag` call warms the
cache for the next session that asks the same thing — no per-user data ever
lands here (see CACHEABLE in mcp_client.py for which tools qualify).

Loaded lazily, exactly like app/retriever.py's Weaviate client, so the
backend still starts and serves chat normally if REDIS_URL is unset or the
Redis server is unreachable — a cache outage must never break chat.

ponytail: single Redis instance, no cluster/sentinel. Fine for one backend
process; add sentinel/cluster config if you outgrow one node.

ponytail: no single-flight lock on a miss, so N concurrent requests for the
same cold key each hit the MCP server once instead of one of them filling
the cache for the rest. Fine at this traffic level (MCP calls are ~seconds,
not the kind of thundering-herd load a lock is worth guarding); add a
SET-NX lock (see Redis's cache-aside guide) if concurrent identical queries
become common enough to matter.
"""
import hashlib
import json
import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

TTL_SECONDS = 2 * 60 * 60  # 2 hours

_client = None
_available: Optional[bool] = None


def _get_client():
    """Lazy-initialize the async Redis client, or None if disabled/unreachable."""
    global _client, _available

    if _available is False:
        return None
    if _client is not None:
        return _client

    if not settings.redis_url:
        _available = False
        logger.info("REDIS_URL not set — MCP result caching disabled")
        return None

    try:
        import redis.asyncio as redis

        _client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        _available = True
        logger.info("Redis cache configured at %s", settings.redis_url)
        return _client
    except Exception as exc:
        _available = False
        logger.error("Redis init failed: %s — MCP result caching disabled", exc)
        return None


def cache_key(fn: str, arguments: str) -> str:
    """Stable key from tool name + JSON arguments (order-independent)."""
    try:
        normalized = json.dumps(json.loads(arguments), sort_keys=True, separators=(",", ":"))
    except (ValueError, TypeError):
        normalized = arguments or ""
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:24]
    return f"mcp:{fn}:{digest}"


async def get(key: str) -> Optional[str]:
    """Return the cached value, or None on a miss/disabled/failure."""
    client = _get_client()
    if client is None:
        return None
    try:
        return await client.get(key)
    except Exception as exc:
        logger.warning("Redis GET failed (%s) — falling back to live MCP call", exc)
        return None


async def set(key: str, value: str, ttl: int = TTL_SECONDS) -> None:
    """Best-effort cache write. Never raises — a failed write just means no cache."""
    client = _get_client()
    if client is None:
        return
    try:
        await client.set(key, value, ex=ttl)
    except Exception as exc:
        logger.warning("Redis SET failed (%s) — result not cached", exc)
