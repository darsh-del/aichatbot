"""Tests for app/mcp_client.py's result post-processing.

Covers the one behavioral difference get_activities_summary has from every
other catalog tool: it is exempt from MAX_TOOL_RESULT_CHARS truncation (see
_postprocess). Everything else still truncates as before.
"""
import json

import pytest
from app.mcp_client import MAX_TOOL_RESULT_CHARS, _postprocess, _active_closure, _DotDict

_BIG_PAYLOAD = json.dumps([{"title": "x" * 200, "_id": str(i)} for i in range(200)])
assert len(_BIG_PAYLOAD) > MAX_TOOL_RESULT_CHARS  # sanity: the fixture is actually big enough


@pytest.mark.asyncio
async def test_get_activities_summary_is_not_truncated():
    result = await _postprocess("get_activities_summary", _BIG_PAYLOAD, {})
    assert len(result["result"]) > MAX_TOOL_RESULT_CHARS
    assert "[truncated" not in result["result"]


@pytest.mark.asyncio
async def test_other_tools_still_get_truncated():
    result = await _postprocess("get_activities", _BIG_PAYLOAD, {})
    assert "[truncated" in result["result"]
    assert len(result["result"]) <= MAX_TOOL_RESULT_CHARS + len("\n...[truncated; use a more specific query or `select`]")

def test_active_closure():
    closures = [
        {"isActive": True, "startDate": "2026-07-01", "endDate": "2026-09-30", "message": "Closed for monsoon"}
    ]
    # Within date
    assert _active_closure(closures, "2026-08-15") is not None
    # Boundary dates
    assert _active_closure(closures, "2026-07-01") is not None
    assert _active_closure(closures, "2026-09-30") is not None
    # Outside dates
    assert _active_closure(closures, "2026-10-01") is None
    
    # Inactive closure
    closures[0]["isActive"] = False
    assert _active_closure(closures, "2026-08-15") is None

    # Empty array
    assert _active_closure([], "2026-08-15") is None


def test_dotdict_supports_dual_access_for_litellm_transform():
    """Regression for a bug that silently broke the get_time_slots closure
    check in production: the supplementary lookup in _postprocess builds a
    fake tool-call object that needs BOTH .function.name (call_catalog_tool
    reads it via attribute) AND ["function"]["name"] (litellm's internal MCP
    transform reads it via subscript). A plain pydantic BaseModel only
    supports the former, so every real call raised
    `TypeError: 'DummyCall' object is not subscriptable`, was swallowed by a
    bare except, and every empty-slots closure check silently fell back to
    the generic "try other providers" hint instead of ever reporting a
    closure. _DotDict (also reused by app.llm for real streamed tool calls)
    supports both.
    """
    from litellm.experimental_mcp_client.tools import (
        transform_openai_tool_call_request_to_mcp_tool_call_request,
    )

    call = _DotDict(function=_DotDict(name="get_activity", arguments='{"identifier": "x"}'))
    assert call.function.name == "get_activity"  # attribute access
    params = transform_openai_tool_call_request_to_mcp_tool_call_request(openai_tool=call)
    assert params.name == "get_activity"  # subscript access under the hood
