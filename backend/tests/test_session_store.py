import asyncio
import time

from app import session_store
from conftest import FakeRedis


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


# --- idle-session scan (dashboard summarization trigger) -------------------


def test_find_idle_sessions_selects_only_idle_unsummarized_with_messages(monkeypatch):
    now = time.time()
    fake = FakeRedis({
        "session:idle": {"message_count": "2", "last_activity": str(now - 1000)},
        "session:recent": {"message_count": "2", "last_activity": str(now - 5)},
        "session:already-summarized": {"message_count": "2", "last_activity": str(now - 1000), "summarized": "true"},
        "session:empty": {"message_count": "0", "last_activity": str(now - 1000)},
    })
    monkeypatch.setattr(session_store, "redis_client", fake)

    assert _run(session_store.find_idle_sessions(600)) == ["idle"]


def test_find_idle_sessions_noop_when_redis_unconfigured(monkeypatch):
    monkeypatch.setattr(session_store, "redis_client", None)
    assert _run(session_store.find_idle_sessions(600)) == []


def test_get_session_data_parses_messages_and_user_info(monkeypatch):
    fake = FakeRedis({
        "session:s1": {
            "messages": '[{"role": "user", "content": "hi"}]',
            "user_info": '{"name": "A", "phone": "123", "email": ""}',
            "message_count": "1",
            "last_activity": "100.0",
        },
    })
    monkeypatch.setattr(session_store, "redis_client", fake)

    data = _run(session_store.get_session_data("s1"))
    assert data["messages"] == [{"role": "user", "content": "hi"}]
    assert data["user_info"] == {"name": "A", "phone": "123", "email": ""}
    assert data["message_count"] == 1


def test_get_session_data_missing_session_returns_empty(monkeypatch):
    monkeypatch.setattr(session_store, "redis_client", FakeRedis({}))
    assert _run(session_store.get_session_data("nope")) == {}


def test_mark_summarized_sets_flag(monkeypatch):
    fake = FakeRedis({"session:s1": {"message_count": "1"}})
    monkeypatch.setattr(session_store, "redis_client", fake)

    _run(session_store.mark_summarized("s1"))
    assert fake._data["session:s1"]["summarized"] == "true"
