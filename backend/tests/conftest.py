"""Shared pytest fixtures.

Sets required env vars *before* app.config is imported anywhere, since
Settings() is instantiated once at module import time. Tests are expected to
run from the backend/ directory so the relative SYSTEM_PROMPT_FILE path
resolves.
"""
import fnmatch
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("LLM_MODEL", "anthropic/claude-sonnet-5")
os.environ.setdefault("SYSTEM_PROMPT_FILE", "data/knowledge_base.md")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")


class FakeRedis:
    """Just enough of redis.asyncio's async API to test session_store /
    dashboard logic without a real Redis server.
    """

    def __init__(self, data: dict | None = None):
        self._data = data or {}  # {key: {field: value}}

    async def hgetall(self, key):
        return self._data.get(key, {})

    async def hset(self, key, field=None, value=None, mapping=None):
        bucket = self._data.setdefault(key, {})
        if mapping:
            bucket.update(mapping)
        if field is not None:
            bucket[field] = value

    async def expire(self, key, seconds):
        pass

    async def scan_iter(self, match="*"):
        for key in list(self._data.keys()):
            if fnmatch.fnmatch(key, match):
                yield key
