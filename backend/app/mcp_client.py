"""Client for bucketlistt's live MCP server — catalog/browse tools only.

Deliberately whitelists only read-only catalog tools (destinations,
experiences, activities, slots, add-ons). Identity, cart, and payment tools
(send_otp, verify_otp, add_to_cart, get_cart, update_cart_item,
remove_from_cart, get_my_bookings, create_payment_link, create_booking_order)
are never loaded, so the model has no way to touch a real account or move
money — those tools simply aren't in the list it's given.
"""
from contextlib import AsyncExitStack, asynccontextmanager

import litellm.experimental_mcp_client as litellm_mcp
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.config import settings

ALLOWED_TOOLS = {
    "get_destinations",
    "get_experiences",
    "get_experience",
    "get_activities",
    "get_activity",
    "search_activities_by_destination_and_tag",
    "get_activity_slots",
    "get_activity_addons",
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


async def call_catalog_tool(session, tool_call) -> dict:
    """Execute one whitelisted catalog tool call against the live MCP server."""
    result = await litellm_mcp.call_openai_tool(session=session, openai_tool=tool_call)
    text = "\n".join(part.text for part in result.content if hasattr(part, "text"))
    return {"result": text or str(result)}
