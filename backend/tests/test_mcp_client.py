"""Tests for app/mcp_client.py's result post-processing.

Covers the one behavioral difference get_activities_summary has from every
other catalog tool: it is exempt from MAX_TOOL_RESULT_CHARS truncation (see
_postprocess). Everything else still truncates as before.
"""
import json

import pytest
from app.mcp_client import MAX_TOOL_RESULT_CHARS, _postprocess, _active_closure

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
