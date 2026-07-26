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
import re
from contextlib import AsyncExitStack, asynccontextmanager

import litellm.experimental_mcp_client as litellm_mcp
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.config import settings

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


@asynccontextmanager
async def mcp_session():
    """Yield a live catalog-tools session, or None if MCP is unconfigured/unreachable.

    Only connection setup is guarded — once yielded, a mid-request failure
    propagates normally and is handled by stream_chat_response's existing
    catch-all, same as any other LLM/tool failure.
    """
    if not settings.mcp_server_url:
        yield None
        return

    async with AsyncExitStack() as stack:
        try:
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(settings.mcp_server_url)
            )
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except Exception as exc:  # pylint: disable=broad-except
            print(f"[mcp_client] unavailable: {exc}. Catalog tools disabled for this request.")
            yield None
            return

        yield session


async def load_catalog_tools(session) -> list[dict]:
    """OpenAI-format schemas for the whitelisted read-only catalog tools only."""
    if session is None:
        return []
    tools = await litellm_mcp.load_mcp_tools(session, format="openai")
    return [t for t in tools if t["function"]["name"] in ALLOWED_TOOLS]


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
    result = await litellm_mcp.call_openai_tool(session=session, openai_tool=tool_call)
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
    return {"result": text}
