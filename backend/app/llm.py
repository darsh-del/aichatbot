"""LLM service layer: system-prompt injection, the tool-calling loop, and
SSE-formatted streaming of the final answer.

RAG pipeline:
  1. The user's latest message is used to semantically search the Weaviate KB.
  2. Retrieved chunks are injected into the system prompt so the LLM can
     answer questions grounded in real Bucketlistt data.
  3. If Weaviate is not configured or the query fails, falls back gracefully
     to the flat `data/knowledge_base.md` system prompt.

Kept free of FastAPI/HTTP concerns so it is unit-testable on its own -
routes in main.py just call `stream_chat_response` and wrap it in a
StreamingResponse.
"""
import asyncio
import json
from datetime import date
from pathlib import Path
from typing import AsyncGenerator

import litellm

from app.config import settings
from app.mcp_client import ALLOWED_TOOLS as MCP_ALLOWED_TOOLS
from app.mcp_client import call_catalog_tool, load_catalog_tools, mcp_session
from app.retriever import retrieve
from app.schemas import ChatMessage
from app.token_store import AUTH_TOOLS, extract_token, get_token, set_token
from app.tools import TOOL_SCHEMAS, dispatch_tool

# ponytail: fixed cap on tool-call round trips rather than unbounded looping -
# guards against a model that never stops requesting tools. Set to 8 so a full
# hierarchy drill-down (experience -> activities -> slots) plus an error-recovery
# retry fits without the loop cutting the model off mid-chain.
MAX_TOOL_ITERATIONS = 8

# Bounds worst-case cost per turn — a normal answer is well under this.
MAX_OUTPUT_TOKENS = 1500


def _load_base_prompt() -> str:
    """Read the base system-prompt / knowledge-base file configured via SYSTEM_PROMPT_FILE."""
    return Path(settings.system_prompt_file).read_text(encoding="utf-8")


def build_messages(chat_messages: list[ChatMessage], session_id: str | None = None) -> list[dict]:
    """Prepend the server-controlled system prompt to the client conversation.

    When Weaviate is configured, the user's latest message is used to retrieve
    semantically relevant KB chunks which are appended to the base system prompt
    (RAG). When Weaviate is unavailable the base file is used as-is.

    Clients can never set/override the system prompt themselves (enforced by
    the ChatMessage role type), so this is the only place a system message
    enters the conversation.
    """
    base_prompt = _load_base_prompt()

    # RAG: retrieve context chunks relevant to the latest user message
    rag_context = ""
    if chat_messages and settings.weaviate_url:
        latest_query = next(
            (m.content for m in reversed(chat_messages) if m.role == "user"),
            "",
        )
        if latest_query:
            rag_context = retrieve(latest_query, top_k=6)

    if rag_context:
        system_content = (
            f"{base_prompt}\n\n"
            "## Relevant Knowledge Base Context\n"
            "Background information only — any seasonal/monsoon closure mentions below "
            "may be outdated. ALWAYS verify availability via `get_time_slots`.\n\n"
            f"{rag_context}"
        )
    else:
        system_content = base_prompt

    # The model has no idea what "today" is (training cutoff) — give it the real
    # date so it can resolve "this weekend", "tomorrow", "next Saturday" into an
    # actual YYYY-MM-DD for slot/availability lookups.
    today = date.today()
    system_content += (
        f"\n\n## Current date\nToday is {today:%A, %B %d, %Y} ({today:%Y-%m-%d}). "
        "Use this to resolve relative dates like 'today', 'tomorrow', 'this weekend', "
        "or 'next Saturday' into a concrete YYYY-MM-DD when a tool needs a date."
    )

    if settings.mcp_server_url:
        system_content += (
            "\n\n## Live Catalog Tools & how to use them\n"
            "You have live, read-only tools that query bucketlistt's real database. Prefer them over "
            "guessing for anything about destinations, providers, activities, prices, timings, or "
            "availability. Never invent these facts.\n\n"
            "**CRITICAL — availability beats seasonal generalizations:** When a user asks about "
            "availability or time slots, ALWAYS call `get_time_slots` for the requested date BEFORE "
            "saying anything is unavailable or closed. The knowledge base may say an activity is "
            "'generally closed' during monsoon or off-season, but operators set their own schedules "
            "and the live tools reflect the real availability. Only tell the user 'no slots' if "
            "`get_time_slots` actually returns zero slots.\n\n"
            "**The data has a hierarchy — learn it, because provider names are NOT activities:**\n"
            "`destination` (city, e.g. Rishikesh) → `experience` = a provider/operator "
            "(e.g. **Splash Bungy**, **Himalayan Bungee**, **Dronecraft River Rafting**) → "
            "`activity` = one specific thing that provider sells (e.g. '117M Bungee Jump', "
            "'16KM Rafting') → `time slots` = bookable times for one activity on one date.\n\n"
            "**Tools by level:** `get_destinations` (cities) · `get_experiences`/`get_experience` "
            "(providers in a city) · `get_activities`/`get_activity` (activities) · "
            "`search_activities_by_destination_and_tag` (find activities by keyword across all "
            "providers) · `get_time_slots` (timings for ONE activityId on ONE date — use THIS for "
            "timings; it needs no login) · `get_activity_addons`. Do NOT pass a `select` argument — it "
            "is unreliable and can return empty; just call the tool without it.\n\n"
            "**Recipes for common questions — follow the whole chain, do not stop early:**\n"
            "- *'what activities does <Provider> offer' / 'list everything at <Provider>' "
            "(e.g. Splash Bungy):* the provider is an EXPERIENCE. Call `get_experiences(destination, "
            "search='<Provider>')` to get its `_id`, then `get_activities(experienceId='<that id>')` "
            "— this returns ONLY that provider's activities. Do NOT use the tag search for a single "
            "provider: it returns EVERY provider in the city and gets truncated, so you'd wrongly "
            "report a different provider's activities. Always pass experienceId (the `experience=` "
            "name form is unreliable and returns nothing).\n"
            "- *'timings / slots for <Provider>':* get the provider's activities as above, pick the "
            "relevant activity's `_id`, then `get_time_slots(activityId, date)` with today's date "
            "(or the user's date). Report the times.\n"
            "- *'find/compare <thing> across providers' (e.g. 'cheapest bungee', 'all rafting "
            "distances'):* THIS is when to use `search_activities_by_destination_and_tag(destination, "
            "tagSearch)` — it spans all providers. Read every provider in the result.\n"
            "- *'price of <X>':* look the activity up via the provider-scoped path or tag search; read "
            "actualPrice (MRP) and discountedPrice (selling).\n"
            "- *'which cities':* `get_destinations`.\n\n"
            "**Never give up after one failed or empty tool call.** If a tool returns 'not found' or "
            "an error hint (e.g. 'try get_activities with experienceId'), FOLLOW the hint and make the "
            "next call — drill down parent→child until you have the answer. Only fall back to 'contact "
            "the operator' or `escalate_and_capture_lead` after you have genuinely tried the drill-down "
            "and it truly has no data.\n"
            "**An empty result in ONE city does not mean the activity doesn't exist.** Different "
            "activities live in different cities (e.g. paragliding is in Mussoorie, not Rishikesh). If "
            "the user names no city and your first search is empty, call `get_destinations` and try the "
            "other likely cities, or ask the user which city — do not conclude it's unavailable after "
            "checking only one.\n\n"
            "**Worked example — 'what activities does Splash Bungy offer':**\n"
            "1. `get_experiences(destination='Rishikesh', search='Splash')` → the Splash Bungy provider "
            "with its `_id`.\n"
            "2. `get_activities(experienceId='<that id>')` → Splash Bungy's OWN activities only "
            "(Splash Bungee 109M, 85M Normal/Freestyle, Tower Top Swing, Zipline, SkyWalk, combos…).\n"
            "3. List them with prices. Do NOT answer from a tag search here — it would mix in other "
            "providers and get truncated. For timings, take an activity's `_id` and call "
            "`get_time_slots(activityId, date=<today>)`.\n\n"
            "For checkout you cannot take payment yourself — after adding to the cart, give the user the "
            "cart link https://www.bucketlistt.com/experiences/cart so they can review and pay there (logged in with "
            "the same phone number)."
        )

    # If this session already authenticated earlier, tell the model so it skips
    # the OTP entirely — the server injects the cached token into cart calls.
    if get_token(session_id):
        system_content += (
            "\n\n## Auth status\nThe user is ALREADY LOGGED IN in this session. Do NOT call send_otp or "
            "verify_otp again and do NOT ask for their phone/OTP — proceed directly with cart and booking "
            "actions. The login token is applied automatically."
        )

    # Final guardrail — placed LAST so it benefits from recency bias.
    # The LLM tends to follow the last instruction most strongly.
    system_content += (
        "\n\n## MANDATORY — DO NOT SKIP\n"
        "Before telling the user ANY activity is unavailable, closed, or affected by "
        "monsoon/weather/season, you MUST call `get_time_slots` for the requested date first. "
        "If the tool returns slots, present them — the tool is ALWAYS more authoritative than "
        "any seasonal text above. NEVER refuse based on season without checking the tool."
    )

    system_message = {"role": "system", "content": system_content}
    return [system_message] + [m.model_dump() for m in chat_messages]


def _inject_auth_token(call, session_id: str | None) -> None:
    """For an authenticated MCP tool, fill in the cached authToken so the user
    isn't re-prompted for an OTP. Mutates call.function.arguments in place."""
    if call.function.name not in AUTH_TOOLS:
        return
    token = get_token(session_id)
    if not token:
        return
    try:
        args = json.loads(call.function.arguments) if call.function.arguments else {}
    except (ValueError, TypeError):
        args = {}
    args["authToken"] = token  # server-owned token always wins over anything the model guessed
    call.function.arguments = json.dumps(args)


async def _run_tool_loop(messages: list[dict], session_id: str | None = None) -> list[dict]:
    """Call the model, executing any requested tool calls, until it stops
    asking for tools (or MAX_TOOL_ITERATIONS is hit).

    Tools come from the local TOOL_SCHEMAS (escalate_and_capture_lead) and, if
    MCP_SERVER_URL is set, bucketlistt's catalog + auth + cart tools. When a
    session already has a cached authToken (from an earlier verify_otp), it is
    injected into authenticated calls so the user isn't asked to re-OTP; a fresh
    token returned by verify_otp is cached for the rest of the session.

    Returns the accumulated message history, ready for a final streamed call.
    """
    async with mcp_session() as session:
        mcp_tools = await load_catalog_tools(session)
        all_tools = TOOL_SCHEMAS + mcp_tools
        # First iteration: MCP catalog + escalate (but NOT search_web — it returns
        # monsoon/seasonal web results that override live tool data).
        first_iter_tools = [
            t for t in all_tools if t["function"]["name"] != "search_web"
        ] if mcp_tools else all_tools
        for iteration in range(MAX_TOOL_ITERATIONS):
            if iteration < 2 and mcp_tools:
                iter_tools = first_iter_tools
                iter_choice = "required"
            else:
                iter_tools = all_tools
                iter_choice = "auto"
            response = await litellm.acompletion(
                model=settings.llm_model,
                messages=messages,
                tools=iter_tools,
                tool_choice=iter_choice,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
            message = response.choices[0].message
            tool_calls = getattr(message, "tool_calls", None)
            if not tool_calls:
                break
            messages.append(message.model_dump())
            for call in tool_calls:
                if call.function.name in MCP_ALLOWED_TOOLS:
                    _inject_auth_token(call, session_id)
                    result = await call_catalog_tool(session, call)
                    if call.function.name == "verify_otp":
                        set_token(session_id, extract_token(result.get("result", "")))
                else:
                    result = await dispatch_tool(call.function.name, call.function.arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.function.name,
                        "content": json.dumps(result),
                    }
                )
    return messages


def _sse(payload: dict) -> str:
    """Format a payload dict as one SSE frame."""
    return f"data: {json.dumps(payload)}\n\n"


def _error_message(exc: BaseException) -> str:
    """Unwrap anyio's TaskGroup ExceptionGroup (from the MCP session) to the real cause."""
    if isinstance(exc, BaseExceptionGroup):
        return _error_message(exc.exceptions[0])
    return str(exc)


async def stream_chat_response(
    chat_messages: list[ChatMessage], session_id: str | None = None
) -> AsyncGenerator[str, None]:
    """Run the tool loop then stream the final answer as SSE frames.

    Always ends with a `done: true` frame - on any failure, that frame
    carries an `error` field instead of the generator raising, so the
    client-side stream never just drops.
    """
    try:
        # build_messages does blocking I/O (a sync OpenAI embedding call + a sync
        # Weaviate query in retrieve()). Running it directly on the event loop
        # serializes every concurrent request behind it, so offload to a thread.
        messages = await asyncio.to_thread(build_messages, chat_messages, session_id)
        messages = await _run_tool_loop(messages, session_id)
        response = await litellm.acompletion(
            model=settings.llm_model,
            messages=messages,
            stream=True,
            max_tokens=MAX_OUTPUT_TOKENS,
        )
        async for chunk in response:
            delta = chunk.choices[0].delta.content or ""
            if delta:
                yield _sse({"delta": delta, "done": False})
        yield _sse({"delta": "", "done": True})
    except Exception as exc:  # pylint: disable=broad-except
        # Any failure (LLM call, tool execution, etc.) must still close the
        # stream with done: true, per the API contract.
        yield _sse({"delta": "", "done": True, "error": _error_message(exc)})
