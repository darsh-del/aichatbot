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
import asyncio
import json
import logging
import re
import time
from contextlib import AsyncExitStack, asynccontextmanager

import litellm.experimental_mcp_client as litellm_mcp
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

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


_persistent_stack: AsyncExitStack | None = None
_persistent_session: ClientSession | None = None
_session_lock = asyncio.Lock()


async def _get_or_create_session() -> ClientSession | None:
    """Return a persistent MCP session, creating one if needed.

    Reuses the same TCP+TLS connection across requests instead of
    opening a new one per user message (~300-500ms saved per request).
    """
    global _persistent_stack, _persistent_session
    if not settings.mcp_server_url:
        return None

    async with _session_lock:
        if _persistent_session is not None:
            return _persistent_session
        t0 = time.perf_counter()
        try:
            stack = AsyncExitStack()
            await stack.__aenter__()
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(settings.mcp_server_url)
            )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            _persistent_stack = stack
            _persistent_session = session
            logger.info("MCP session established in %.3fs — %s", time.perf_counter() - t0, settings.mcp_server_url)
            return session
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("MCP unavailable after %.3fs: %s — catalog tools disabled", time.perf_counter() - t0, exc)
            return None


async def close_persistent_session() -> None:
    """Tear down the persistent MCP session (called on app shutdown)."""
    global _persistent_stack, _persistent_session
    async with _session_lock:
        if _persistent_stack:
            await _persistent_stack.aclose()
        _persistent_stack = None
        _persistent_session = None


async def _reset_session() -> None:
    """Force-close and recreate the session on next call (after a mid-request failure)."""
    global _persistent_stack, _persistent_session
    async with _session_lock:
        if _persistent_stack:
            try:
                await _persistent_stack.aclose()
            except Exception:  # pylint: disable=broad-except
                pass
        _persistent_stack = None
        _persistent_session = None


@asynccontextmanager
async def mcp_session():
    """Yield a live catalog-tools session, or None if MCP is unconfigured/unreachable.

    Uses a persistent connection; if the session fails mid-request, the caller's
    error handling catches it and the next request will create a fresh session.
    """
    session = await _get_or_create_session()
    try:
        yield session
    except Exception:
        await _reset_session()
        raise


# -- Tool schema cache (schemas don't change at runtime) ---------------------
_cached_tools: list[dict] = []
_tools_cached_at: float = 0.0
_TOOLS_CACHE_TTL = 300  # 5 minutes


async def load_catalog_tools(session) -> list[dict]:
    """OpenAI-format schemas for the whitelisted catalog tools.

    Cached in-memory for 5 minutes — avoids a network round-trip to the MCP
    server on every single user message.
    """
    global _cached_tools, _tools_cached_at
    if session is None:
        return []
    now = time.monotonic()
    if _cached_tools and (now - _tools_cached_at) < _TOOLS_CACHE_TTL:
        logger.debug("MCP tool schemas served from cache (%d tools)", len(_cached_tools))
        return _cached_tools
    t0 = time.perf_counter()
    tools = await litellm_mcp.load_mcp_tools(session, format="openai")
    _cached_tools = [t for t in tools if t["function"]["name"] in ALLOWED_TOOLS]
    _tools_cached_at = now
    logger.info("Loaded %d MCP tool schemas (of %d total) in %.3fs", len(_cached_tools), len(tools), time.perf_counter() - t0)
    return _cached_tools


# Hard ceiling per tool result — only hit after field-stripping, as a last resort.
# Sized so a full multi-provider search (e.g. all rafting distances across both
# providers) survives slimming without truncation dropping later providers.
MAX_TOOL_RESULT_CHARS = 16000

# Bulky, model-useless fields to drop from tool results. These (image/media URL
# arrays, HTML blobs) are most of the payload size; stripping them keeps the
# useful fields (title, _id, prices, distances, slots, phone) so a multi-provider
# result still fits without blind truncation cutting off later providers — which
# was hiding the 24km rafting option behind Dronecraft's media bulk.
_DROP_KEYS = {
    "media", "images", "primaryMedia", "logo", "image", "__v", "clientId",
    # pure metadata never needed to answer a user question
    "createdAt", "updatedAt", "uniqueCode", "advancePercentage", "highlightedOrder",
    "order", "forAgent", "isHighlighted", "isApproved", "category", "address",
    # timeSlots arrays are the single biggest bulk and are NOT needed here — actual
    # bookable times come from get_activity_slots (returns them under data.slots).
    # Dropping them lets a multi-provider search fit without truncating later providers.
    "timeSlots",
}
_HTML_KEYS = {"description", "highlights", "inclusion", "exclusion", "subtitle"}
_HTML_RE = re.compile(r"<[^>]+>")


def _slim(obj):
    """Recursively drop media/HTML bulk from an MCP JSON result."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in _DROP_KEYS:
                continue
            if k in _HTML_KEYS and isinstance(v, str):
                out[k] = _HTML_RE.sub("", v).strip()[:300]
            else:
                out[k] = _slim(v)
        return out
    if isinstance(obj, list):
        return [_slim(x) for x in obj]
    return obj


async def call_catalog_tool(session, tool_call) -> dict:
    """Execute one whitelisted catalog tool call against the live MCP server."""
    fn = tool_call.function.name
    t0 = time.perf_counter()
    result = await litellm_mcp.call_openai_tool(session=session, openai_tool=tool_call)
    logger.info("MCP call %s completed in %.3fs", fn, time.perf_counter() - t0)
    text = "\n".join(part.text for part in result.content if hasattr(part, "text"))
    text = text or str(result)
    # Strip bulky fields first (keeps useful data, shrinks size a lot); only if it
    # still exceeds the ceiling do we hard-truncate as a fallback.
    try:
        text = json.dumps(_slim(json.loads(text)), separators=(",", ":"))
    except (ValueError, TypeError):
        pass
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + "\n...[truncated; use a more specific query or `select`]"
    result = {"result": text}
    fn = tool_call.function.name
    # After a search, nudge the model to check actual time slots.
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
