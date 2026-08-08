import asyncio
import json

from app import dashboard, session_store
from conftest import FakeRedis


def _run(coro):
    return asyncio.run(coro)


class _FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, input_dict):
        self.input = input_dict


class _FakeSummaryResponse:
    def __init__(self, input_dict):
        self.content = [_FakeToolUseBlock(input_dict)]


_FAKE_FIELDS = {
    "summary": "User asked about bungee jumping prices in Rishikesh.",
    "topics": ["bungee jumping"],
    "questions_asked": ["How much is bungee jumping?"],
    "sentiment": "positive",
    "requires_followup": False,
}


# --- summary generation ------------------------------------------------


def test_generate_summary_parses_tool_use_block(monkeypatch):
    async def fake_create(**kwargs):
        assert kwargs["tool_choice"] == {"type": "tool", "name": "submit_conversation_summary"}
        return _FakeSummaryResponse(_FAKE_FIELDS)

    fake_client = type("C", (), {"messages": type("M", (), {"create": staticmethod(fake_create)})()})()
    monkeypatch.setattr(dashboard, "get_aclient", lambda: fake_client)

    result = _run(dashboard._generate_summary([{"role": "user", "content": "hi"}]))
    assert result == _FAKE_FIELDS


# --- storage (isolated from the real data/session_summaries.json) -------


def test_append_and_list_and_get_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(dashboard, "SUMMARIES_FILE", tmp_path / "session_summaries.json")

    record = {"session_id": "s1", "ended_at": "2026-08-08T00:00:00Z", **_FAKE_FIELDS}
    dashboard._append_summary(record)

    assert dashboard.list_summaries() == [record]
    assert dashboard.get_summary("s1") == record
    assert dashboard.get_summary("nope") is None


def test_list_summaries_filters_by_since(monkeypatch, tmp_path):
    monkeypatch.setattr(dashboard, "SUMMARIES_FILE", tmp_path / "session_summaries.json")
    dashboard._append_summary({"session_id": "old", "ended_at": "2026-08-01T00:00:00Z"})
    dashboard._append_summary({"session_id": "new", "ended_at": "2026-08-08T00:00:00Z"})

    result = dashboard.list_summaries(since="2026-08-05T00:00:00Z")
    assert [r["session_id"] for r in result] == ["new"]


# --- end-to-end idle scan -------------------------------------------------


def test_summarize_idle_sessions_appends_and_marks_summarized(monkeypatch, tmp_path):
    monkeypatch.setattr(dashboard, "SUMMARIES_FILE", tmp_path / "session_summaries.json")

    fake_redis = FakeRedis({
        "session:s1": {
            "messages": json.dumps([{"role": "user", "content": "How much is bungee jumping?"}]),
            "user_info": json.dumps({"name": "Rahul", "phone": "123", "email": ""}),
            "message_count": "1",
            "last_activity": "1000.0",
        },
    })
    monkeypatch.setattr(session_store, "redis_client", fake_redis)
    monkeypatch.setattr(session_store, "find_idle_sessions", lambda idle_seconds: _async_list(["s1"]))

    async def fake_create(**kwargs):
        return _FakeSummaryResponse(_FAKE_FIELDS)

    fake_client = type("C", (), {"messages": type("M", (), {"create": staticmethod(fake_create)})()})()
    monkeypatch.setattr(dashboard, "get_aclient", lambda: fake_client)

    count = _run(dashboard.summarize_idle_sessions())

    assert count == 1
    stored = dashboard.list_summaries()
    assert len(stored) == 1
    assert stored[0]["session_id"] == "s1"
    assert stored[0]["user_info"] == {"name": "Rahul", "phone": "123", "email": ""}
    assert stored[0]["summary"] == _FAKE_FIELDS["summary"]
    assert fake_redis._data["session:s1"]["summarized"] == "true"


def test_summarize_idle_sessions_skips_empty_transcript(monkeypatch, tmp_path):
    monkeypatch.setattr(dashboard, "SUMMARIES_FILE", tmp_path / "session_summaries.json")
    fake_redis = FakeRedis({
        "session:empty": {"messages": "[]", "message_count": "0", "last_activity": "1000.0"},
    })
    monkeypatch.setattr(session_store, "redis_client", fake_redis)
    monkeypatch.setattr(session_store, "find_idle_sessions", lambda idle_seconds: _async_list(["empty"]))

    count = _run(dashboard.summarize_idle_sessions())

    assert count == 1  # scanned, but nothing generated
    assert dashboard.list_summaries() == []
    assert fake_redis._data["session:empty"]["summarized"] == "true"


async def _async_list(value):
    return value
