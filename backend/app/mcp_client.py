"""Client for bucketlistt's live MCP server — catalog + auth + cart tier.

Whitelists browse tools (destinations, experiences, activities, slots, add-ons),
OTP-based auth (send_otp, verify_otp), and cart management (add_to_cart, get_cart,
update_cart_item, remove_from_cart), plus read-only get_my_bookings.

**Payment tools (create_payment_link, create_booking_order) remain excluded** —
the bot can build a cart for the user, but the actual charge happens on
bucketlistt.com, not through the chatbot. This keeps the money-moving surface
zero-sized while still letting the bot do the useful pre-checkout work.

The authToken from verify_otp flows through the conversation naturally — the
LLM sees it in the tool result and passes it into subsequent authenticated
tool calls. Each user's token is scoped to their conversation.
"""
import json
import logging
import re
import time
from contextlib import AsyncExitStack

import litellm.experimental_mcp_client as litellm_mcp
from mcp import ClientSession
try:
    from mcp.client.streamable_http import streamablehttp_client
except ImportError:
    from mcp.client.streamable_http import streamable_http_client as streamablehttp_client

from app.config import settings

logger = logging.getLogger(__name__)

ALLOWED_TOOLS = {
    # Browse (read-only, no auth)
    "get_destinations",
    "get_experiences",
    "get_experience",
    "get_activities",
    "get_activity",
    "search_activities_by_destination_and_tag",
    "get_activity_slots",
    "get_time_slots",  # auth-free twin of get_activity_slots; preferred for timings
    "get_activity_addons",
    # Auth (SMS OTP login only)
    "send_otp",
    "verify_otp",
    # Cart (build up an order, no payment)
    "add_to_cart",
    "get_cart",
    "update_cart_item",
    "remove_from_cart",
    # Post-book read
    "get_my_bookings",
}


async def _fresh_session():
    """Create a fresh MCP session. Returns (stack, session).

    Caller MUST call stack.aclose() when done — never hold the session across
    an async generator yield, or anyio cancel scopes will leak into Starlette's
    task groups and crash the streaming response.
    """
    stack = AsyncExitStack()
    await stack.__aenter__()
    read, write, _ = await stack.enter_async_context(
        streamablehttp_client(settings.mcp_server_url)
    )
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return stack, session


# -- Tool schema cache (schemas don't change at runtime) ---------------------
_cached_tools: list[dict] = []
_tools_cached_at: float = 0.0
_TOOLS_CACHE_TTL = 300  # 5 minutes


async def load_catalog_tools() -> list[dict]:
    """OpenAI-format schemas for the whitelisted catalog tools.

    Cached in-memory for 5 minutes — avoids a network round-trip to the MCP
    server on every single user message.
    """
    global _cached_tools, _tools_cached_at
    if not settings.mcp_server_url:
        return []
    now = time.monotonic()
    if _cached_tools and (now - _tools_cached_at) < _TOOLS_CACHE_TTL:
        logger.debug("MCP tool schemas served from cache (%d tools)", len(_cached_tools))
        return _cached_tools
    t0 = time.perf_counter()
    stack, session = await _fresh_session()
    try:
        tools = await litellm_mcp.load_mcp_tools(session, format="openai")
        _cached_tools = [t for t in tools if t["function"]["name"] in ALLOWED_TOOLS]
        _tools_cached_at = now
        logger.info("Loaded %d MCP tool schemas (of %d total) in %.3fs", len(_cached_tools), len(tools), time.perf_counter() - t0)
    finally:
        try:
            await stack.aclose()
        except Exception:
            pass
    return _cached_tools


# Hard ceiling per tool result — only hit after field-stripping, as a last resort.
MAX_TOOL_RESULT_CHARS = 16000

_DROP_KEYS = {
    "media", "images", "primaryMedia", "logo", "image", "__v", "clientId",
    "createdAt", "updatedAt", "uniqueCode", "advancePercentage", "highlightedOrder",
    "order", "forAgent", "isHighlighted", "isApproved", "category",
    "timeSlots",
}
_HTML_KEYS = {"description", "highlights", "inclusion", "exclusion", "subtitle", "eligibility"}
_HTML_RE = re.compile(r"<[^>]+>")
# Longer limit for fields that carry critical differentiating info (inclusions, descriptions).
_HTML_TRUNC_LONG = 800
_HTML_TRUNC_SHORT = 300
_LONG_HTML_KEYS = {"description", "inclusion", "exclusion", "highlights"}

_SEARCH_KEEP = {"_id", "title", "actualPrice", "discountedPrice", "subtitle"}


def _slim(obj):
    """Recursively drop media/HTML bulk from an MCP JSON result."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in _DROP_KEYS:
                continue
            if k in _HTML_KEYS and isinstance(v, str):
                limit = _HTML_TRUNC_LONG if k in _LONG_HTML_KEYS else _HTML_TRUNC_SHORT
                out[k] = _HTML_RE.sub("", v).strip()[:limit]
            else:
                out[k] = _slim(v)
        return out
    if isinstance(obj, list):
        return [_slim(x) for x in obj]
    return obj


def _compact_search(raw):
    """Reduce a tag-search result to provider names + activity summaries.

    Keeps subtitle and a short description snippet so the LLM can
    differentiate activities (e.g. Dronecraft's drone+DSLR coverage vs plain
    rafting) without needing a follow-up get_activity call.
    """
    if not isinstance(raw, dict) or "data" not in raw:
        return _slim(raw)
    out = {k: v for k, v in raw.items() if k != "data"}
    out["data"] = []
    for group in raw.get("data", []):
        if not isinstance(group, dict):
            out["data"].append(group)
            continue
        activities = []
        for act in group.get("activities", []):
            if not isinstance(act, dict):
                continue
            item = {k: v for k, v in act.items() if k in _SEARCH_KEEP}
            # Keep a description snippet so the LLM sees what makes each
            # activity unique (drone coverage, included perks, etc.)
            desc = act.get("description", "")
            if isinstance(desc, str) and desc:
                item["description"] = _HTML_RE.sub("", desc).strip()[:200]
            inclusion = act.get("inclusion", "")
            if isinstance(inclusion, str) and inclusion:
                item["inclusion"] = _HTML_RE.sub("", inclusion).strip()[:200]
            activities.append(item)
        compact = {
            "experience": group.get("experience"),
            "experienceId": group.get("experienceId"),
            "activities": activities,
        }
        out["data"].append(compact)
    return out


def _postprocess(fn: str, text: str) -> dict:
    """Slim, truncate, and add hints to a tool result."""
    raw_len = len(text)
    try:
        parsed = json.loads(text)
        if fn == "search_activities_by_destination_and_tag":
            text = json.dumps(_compact_search(parsed), separators=(",", ":"))
        else:
            text = json.dumps(_slim(parsed), separators=(",", ":"))
    except (ValueError, TypeError):
        pass
    slimmed_len = len(text)
    truncated = slimmed_len > MAX_TOOL_RESULT_CHARS
    if truncated:
        text = text[:MAX_TOOL_RESULT_CHARS] + "\n...[truncated; use a more specific query or `select`]"
    logger.info("MCP result %s: %d raw, %d slimmed%s", fn, raw_len, slimmed_len, f", TRUNCATED at {MAX_TOOL_RESULT_CHARS}" if truncated else "")
    result = {"result": text}
    if fn == "search_activities_by_destination_and_tag":
        result["_hint"] = (
            "These are activity listings, NOT availability. To check if an activity "
            "is available on a specific date, call get_time_slots(activityId, date)."
        )
    if fn in ("get_time_slots", "get_activity_slots"):
        if '"slots":[]' in text.replace(" ", ""):
            result["_hint"] = (
                "Zero slots for THIS activity. Other providers may offer the same "
                "activity type with available slots — call search_activities_by_destination_and_tag "
                "to find alternatives before telling the user it's unavailable."
            )
        else:
            result["_hint"] = (
                "Show ONLY the slot start time (e.g. '10:00 AM'). Do NOT show or "
                "fabricate an end time — the data does not have meaningful end times."
            )
    return result


async def call_catalog_tool(tool_call) -> dict:
    """Execute one whitelisted catalog tool call against the live MCP server.

    Creates a fresh session per call so anyio cancel scopes are fully contained
    and never leak into the caller's task (which would crash Starlette's
    streaming response).
    """
    fn = tool_call.function.name
    t0 = time.perf_counter()
    stack, session = await _fresh_session()
    try:
        result = await litellm_mcp.call_openai_tool(session=session, openai_tool=tool_call)
    finally:
        try:
            await stack.aclose()
        except Exception:
            pass
    logger.info("MCP call %s completed in %.3fs", fn, time.perf_counter() - t0)
    text = "\n".join(part.text for part in result.content if hasattr(part, "text"))
    text = text or str(result)
    return _postprocess(fn, text)
