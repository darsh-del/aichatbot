"""Tests for app/mcp_client.py's result post-processing.

Covers the one behavioral difference get_activities_summary has from every
other catalog tool: it is exempt from MAX_TOOL_RESULT_CHARS truncation (see
_postprocess). Everything else still truncates as before.
"""
import json

from app.mcp_client import MAX_TOOL_RESULT_CHARS, _postprocess

_BIG_PAYLOAD = json.dumps([{"title": "x" * 200, "_id": str(i)} for i in range(200)])
assert len(_BIG_PAYLOAD) > MAX_TOOL_RESULT_CHARS  # sanity: the fixture is actually big enough


def test_get_activities_summary_is_not_truncated():
    result = _postprocess("get_activities_summary", _BIG_PAYLOAD)
    assert len(result["result"]) > MAX_TOOL_RESULT_CHARS
    assert "[truncated" not in result["result"]


def test_other_tools_still_get_truncated():
    result = _postprocess("get_activities", _BIG_PAYLOAD)
    assert "[truncated" in result["result"]
    assert len(result["result"]) <= MAX_TOOL_RESULT_CHARS + len("\n...[truncated; use a more specific query or `select`]")
