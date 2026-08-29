import asyncio

from app import cache


def test_cache_key_is_stable_regardless_of_arg_order():
    k1 = cache.cache_key("get_activity", '{"id": "1", "date": "2026-08-06"}')
    k2 = cache.cache_key("get_activity", '{"date": "2026-08-06", "id": "1"}')
    assert k1 == k2


def test_cache_key_differs_for_different_args_or_tool():
    a = cache.cache_key("get_activity", '{"id": "1"}')
    b = cache.cache_key("get_activity", '{"id": "2"}')
    c = cache.cache_key("get_activities", '{"id": "1"}')
    assert len({a, b, c}) == 3


def test_cache_key_handles_bad_json():
    # Must not raise even if arguments isn't valid JSON.
    assert cache.cache_key("fn", "not json") == cache.cache_key("fn", "not json")


def test_get_set_noop_when_redis_unconfigured(monkeypatch):
    # Ensure REDIS_URL is strictly None regardless of what .env says,
    # so caching is disabled — get/set must be harmless no-ops.
    monkeypatch.setattr(cache.settings, "redis_url", None)
    # Also reset the module-level singleton state so it re-evaluates
    monkeypatch.setattr(cache, "_client", None)
    monkeypatch.setattr(cache, "_available", None)
    
    async def roundtrip():
        await cache.set("mcp:test:key", "value")
        return await cache.get("mcp:test:key")

    assert asyncio.run(roundtrip()) is None
