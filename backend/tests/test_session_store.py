import asyncio

from app import session_store


class _FakeRedis:
    """Just enough of redis.asyncio's async API for _prompt_eligible."""

    def __init__(self, data: dict):
        self._data = data

    async def hgetall(self, key):
        return self._data.get(key, {})


def _run(coro):
    return asyncio.run(coro)


def test_noop_when_redis_unconfigured(monkeypatch):
    monkeypatch.setattr(session_store, "redis_client", None)
    assert _run(session_store.should_prompt_login("s1")) is False
    assert _run(session_store.should_nudge_for_contact("s1")) is False


def test_nudge_fires_one_turn_before_the_legacy_prompt_flag(monkeypatch):
    # should_nudge_for_contact is checked BEFORE the Nth response is
    # generated (count = threshold - 1 already saved); should_prompt_login
    # is checked AFTER it's saved (count = threshold). Same turn, two
    # different checkpoints — this pins that ordering.
    threshold = session_store.settings.login_prompt_after

    monkeypatch.setattr(
        session_store, "redis_client",
        _FakeRedis({"session:s1": {"message_count": str(threshold - 1)}}),
    )
    assert _run(session_store.should_nudge_for_contact("s1")) is True
    assert _run(session_store.should_prompt_login("s1")) is False

    monkeypatch.setattr(
        session_store, "redis_client",
        _FakeRedis({"session:s1": {"message_count": str(threshold)}}),
    )
    assert _run(session_store.should_prompt_login("s1")) is True


def test_no_nudge_once_prompted_or_info_already_captured(monkeypatch):
    monkeypatch.setattr(
        session_store, "redis_client",
        _FakeRedis({"session:s1": {"message_count": "10", "login_prompted": "true"}}),
    )
    assert _run(session_store.should_nudge_for_contact("s1")) is False

    monkeypatch.setattr(
        session_store, "redis_client",
        _FakeRedis({"session:s1": {"message_count": "10", "user_info": "{}"}}),
    )
    assert _run(session_store.should_nudge_for_contact("s1")) is False
