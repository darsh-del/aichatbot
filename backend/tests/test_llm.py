"""Tests for the bungee-summary tool gate in app/llm.py.

get_activities_summary must only ever be offered to the LLM when the user's
latest message is about bungee jumping — see app/llm.py::_wants_bungee_summary.
"""
import asyncio

import pytest

from app.llm import _wants_bungee_summary


@pytest.mark.parametrize("text", [
    "What are the bungee jumping prices in Rishikesh?",
    "bungy options?",
    "Tell me about Bungee",
    "BUNGIE combo price",
])
def test_bungee_query_triggers_gate(text):
    assert _wants_bungee_summary([{"role": "user", "content": text}])


def test_non_bungee_query_does_not_trigger_gate():
    assert not _wants_bungee_summary([{"role": "user", "content": "What rafting packages do you have?"}])


def test_only_latest_user_message_is_checked():
    messages = [
        {"role": "user", "content": "bungee prices?"},
        {"role": "assistant", "content": "Here are the bungee options..."},
        {"role": "user", "content": "what about rafting instead"},
    ]
    assert not _wants_bungee_summary(messages)


def test_empty_messages_does_not_trigger_gate():
    assert not _wants_bungee_summary([])


# --- end-to-end: the tool actually leaves the list sent to the LLM --------

_FAKE_MCP_TOOLS = [
    {"type": "function", "function": {"name": "get_activities", "parameters": {}}},
    {"type": "function", "function": {"name": "get_activities_summary", "parameters": {}}},
]


class _ImmediateFinalAnswer:
    """Fake non-tool-call chunk stream — ends the loop after one LLM call."""

    def __init__(self):
        self._sent = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._sent:
            raise StopAsyncIteration
        self._sent = True
        choice = type("C", (), {"delta": type("D", (), {"content": "hi", "tool_calls": None})()})
        return type("Chunk", (), {"choices": [choice]})()


async def _collect_tool_names_seen(messages: list[dict], monkeypatch) -> list[str]:
    """Drive one _run_tool_loop pass and return the tool names offered on the
    first LLM call."""
    import app.llm as llm

    monkeypatch.setattr(llm, "load_catalog_tools", lambda: _async_return(_FAKE_MCP_TOOLS))
    seen_tool_names = []

    async def _fake_acompletion(*_args, **kwargs):
        seen_tool_names.append([t["function"]["name"] for t in kwargs["tools"]])
        return _ImmediateFinalAnswer()

    monkeypatch.setattr(llm.litellm, "acompletion", _fake_acompletion)

    async for _ in llm._run_tool_loop(messages):
        pass
    return seen_tool_names[0]


async def _async_return(value):
    return value


def test_tool_loop_excludes_bungee_summary_for_non_bungee_query(monkeypatch):
    messages = [{"role": "user", "content": "What rafting packages do you have?"}]
    tool_names = asyncio.run(_collect_tool_names_seen(messages, monkeypatch))

    assert "get_activities_summary" not in tool_names
    assert "get_activities" in tool_names


def test_tool_loop_includes_bungee_summary_for_bungee_query(monkeypatch):
    messages = [{"role": "user", "content": "bungee jumping prices?"}]
    tool_names = asyncio.run(_collect_tool_names_seen(messages, monkeypatch))

    assert "get_activities_summary" in tool_names
