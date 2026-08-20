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
import logging
import re
import time
from datetime import date
from pathlib import Path
from typing import AsyncGenerator

import litellm

from app.config import settings

logger = logging.getLogger(__name__)
from app.mcp_client import ALLOWED_TOOLS as MCP_ALLOWED_TOOLS
from app.mcp_client import BUNGEE_SUMMARY_TOOL, _DotDict, call_catalog_tool, load_catalog_tools
from app.retriever import retrieve
from app.schemas import ChatMessage
from app.token_store import AUTH_TOOLS, extract_token, get_token, set_token
from app.tools import TOOL_SCHEMAS, dispatch_tool
from app.session_store import save_turn, should_prompt_login, mark_login_prompted, should_nudge_for_contact

MAX_TOOL_ITERATIONS = 8
MAX_OUTPUT_TOKENS = 1500

# Matches bungee/bungy/bungie, case-insensitive — the only trigger for
# exposing BUNGEE_SUMMARY_TOOL to the LLM (see _wants_bungee_summary).
_BUNGEE_RE = re.compile(r"bung(?:ee|y|ie)?", re.IGNORECASE)


def _wants_bungee_summary(messages: list[dict]) -> bool:
    """True only if the latest user message is about bungee jumping.

    Deterministic gate, not left to the LLM's judgment: BUNGEE_SUMMARY_TOOL
    is a compact, bungee-only shape (no location/media) — offering it for
    every topic would just reproduce the old over-fetch problem elsewhere.
    """
    latest_user = next(
        (m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    return bool(_BUNGEE_RE.search(latest_user))


# -- Cached base prompt (file doesn't change at runtime) ---------------------
_base_prompt_cache: str | None = None


def _load_base_prompt() -> str:
    global _base_prompt_cache
    if _base_prompt_cache is None:
        _base_prompt_cache = Path(settings.system_prompt_file).read_text(encoding="utf-8")
    return _base_prompt_cache


def build_messages(
    chat_messages: list[ChatMessage],
    session_id: str | None = None,
    nudge_contact: bool = False,
) -> list[dict]:
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
            "`get_activities_summary` (compact bungee-only list — see the bungee recipe below; "
            "only offered to you when the user's message is about bungee) · "
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
            "- *'which cities':* `get_destinations`.\n"
            "- *'bungee in Rishikesh' / 'bungee prices' / 'bungee options':* use "
            "`get_activities_summary(destination='Rishikesh', tagSearch='bungee')` — a compact "
            "tool made specifically for bungee (avoids the large data dump `search_activities_by_"
            "destination_and_tag` used to send) — and present ALL providers (Himalayan Bungee, "
            "Splash Bungy, Jumpin Heights, Maa Ganga Bungee, Thrill Factory) with prices. Never show "
            "only one provider. If the user then asks for MORE detail than the summary has (full "
            "description, exact location, media, certifications), call `get_activity(identifier=...)` "
            "on that one activity's `_id` for the complete record — do not guess missing fields.\n"
            "- *'paragliding':* search with tagSearch='paragliding' across destinations. Paragliding "
            "typically has SHORT and LONG flight options — always present both with prices and let the "
            "user choose.\n"
            "- *'kids activities' / 'family activities':* search the catalog, and if no specific "
            "kid-friendly results, use `search_web` — do NOT show unrelated results like Ganga Aarti.\n\n"
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
            "**Dronecraft River Rafting — perks are in the tool result:**\n"
            "When a catalog tool result contains a `_dronecraft_perks` field, use THAT list as the "
            "definitive perks for Dronecraft — not the `inclusion` field from the catalog data. The "
            "inclusion field is trimmed and may contain wrong items (e.g. 'lounge access'). The "
            "`_dronecraft_perks` hint is the verified, complete list.\n\n"
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

    # One-time nudge, checked by the caller BEFORE this turn's response is
    # generated — no special frontend flag needed, the ask just rides inside
    # the normal answer text.
    if nudge_contact:
        system_content += (
            "\n\n## One-time nudge — ask for contact info\n"
            "This is a good moment to warmly ask the user for their name and phone "
            "number (email optional) so you can save this itinerary/answer and flag "
            "them for VIP slots & discounts. Add ONE friendly sentence for this at "
            "the end of your answer above — don't make it the whole response, and "
            "don't repeat this ask again in later turns. If they share their name, "
            "phone, or email in a future message, call `escalate_and_capture_lead` "
            "with urgency='normal' to save it."
        )

    # Final guardrail — placed LAST so it benefits from recency bias.
    # The LLM tends to follow the last instruction most strongly.
    system_content += (
        "\n\n## MANDATORY — DO NOT SKIP\n"
        "Seasonal closures are authoritative and explicitly returned by the tools as "
        "`_closed_until` and `_closure_reason`. If a tool shows an activity is closed, trust it "
        "and inform the user of the reason and reopen date. If an activity is closed, do NOT "
        "suggest alternatives from the exact same category (e.g. another rafting route) without "
        "first checking if they are open, as the entire category is likely closed."
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


_TOOL_STATUS_LABELS = {
    "get_destinations": "Fetching destinations…",
    "get_experiences": "Looking up providers…",
    "get_experience": "Looking up provider…",
    "get_activities": "Fetching activities…",
    "get_activity": "Fetching activity details…",
    "search_activities_by_destination_and_tag": "Searching activities…",
    "get_activity_slots": "Checking availability…",
    "get_time_slots": "Checking time slots…",
    "get_activity_addons": "Fetching add-ons…",
    "send_otp": "Sending OTP…",
    "verify_otp": "Verifying OTP…",
    "add_to_cart": "Adding to cart…",
    "get_cart": "Fetching cart…",
    "update_cart_item": "Updating cart…",
    "remove_from_cart": "Removing from cart…",
    "get_my_bookings": "Fetching bookings…",
    "search_web": "Searching the web…",
    "escalate_and_capture_lead": "Creating support ticket…",
}


async def _execute_tool(call, session_id: str | None) -> dict:
    """Execute a single tool call and return the result dict."""
    tool_name = call.function.name
    t0 = time.perf_counter()
    logger.info("Executing tool: %s  args=%s", tool_name, call.function.arguments[:200] if call.function.arguments else "")
    try:
        if tool_name in MCP_ALLOWED_TOOLS:
            _inject_auth_token(call, session_id)
            result = await call_catalog_tool(call)
            if tool_name == "verify_otp":
                set_token(session_id, extract_token(result.get("result", "")))
        else:
            result = await dispatch_tool(tool_name, call.function.arguments, session_id)
        elapsed = time.perf_counter() - t0
        logger.info("Tool %s completed in %.3fs", tool_name, elapsed)
        return result
    except Exception:
        logger.exception("Tool %s failed after %.3fs", tool_name, time.perf_counter() - t0)
        raise


async def _run_tool_loop(
    messages: list[dict],
    session_id: str | None = None,
) -> AsyncGenerator[str | tuple[str, str], None]:
    """Run the tool-calling loop as an async generator.

    Every LLM call uses stream=True so the final answer streams token-by-token
    via yield ("delta", text).  Tool calls are reassembled from stream chunks
    transparently.  Status strings are yielded as plain strings.
    """
    t_loop_start = time.perf_counter()
    mcp_tools = await load_catalog_tools()
    bungee_query = _wants_bungee_summary(messages)
    if not bungee_query:
        mcp_tools = [t for t in mcp_tools if t["function"]["name"] != BUNGEE_SUMMARY_TOOL]
    logger.info(
        "[bungee-summary] tool %s this turn", "enabled" if bungee_query else "disabled (non-bungee query)"
    )
    logger.info("Loaded %d MCP tools, %d local tools", len(mcp_tools), len(TOOL_SCHEMAS))
    all_tools = TOOL_SCHEMAS + mcp_tools
    first_iter_tools = [
        t for t in all_tools if t["function"]["name"] != "search_web"
    ] if mcp_tools else all_tools
    for iteration in range(MAX_TOOL_ITERATIONS):
        if iteration < 1 and mcp_tools:
            iter_tools = first_iter_tools
            iter_choice = "required"
        else:
            iter_tools = all_tools
            iter_choice = "auto"
        t_llm = time.perf_counter()
        response = await litellm.acompletion(
            model=settings.llm_model,
            messages=messages,
            tools=iter_tools,
            tool_choice=iter_choice,
            max_tokens=MAX_OUTPUT_TOKENS,
            num_retries=2,
            timeout=30,
            stream=True,
        )

        # Consume the stream: yield content deltas in real-time, collect tool
        # calls incrementally so we can execute them after the stream ends.
        full_content = ""
        tc_parts: dict[int, dict] = {}
        async for chunk in response:
            choices = chunk.choices
            if not choices:
                continue
            delta = choices[0].delta
            if delta.content:
                full_content += delta.content
                yield ("delta", delta.content)
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tc_parts:
                        tc_parts[idx] = {"id": "", "function": {"name": "", "arguments": ""}}
                    if tc.id:
                        tc_parts[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tc_parts[idx]["function"]["name"] += tc.function.name
                        if tc.function.arguments:
                            tc_parts[idx]["function"]["arguments"] += tc.function.arguments

        logger.info("Tool-loop LLM call #%d took %.3fs (choice=%s)", iteration, time.perf_counter() - t_llm, iter_choice)

        if not tc_parts:
            logger.info("Tool loop done after %d iterations, streamed %d chars", iteration + 1, len(full_content))
            break

        # Reconstruct tool call objects that support both obj.key and obj["key"]
        # (litellm internals use dict-style access on tool calls)
        tool_calls = [
            _DotDict(
                id=tc_parts[i]["id"],
                type="function",
                function=_DotDict(
                    name=tc_parts[i]["function"]["name"],
                    arguments=tc_parts[i]["function"]["arguments"],
                ),
            )
            for i in sorted(tc_parts)
        ]
        messages.append({
            "role": "assistant",
            "content": full_content or None,
            "tool_calls": [
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in tool_calls
            ],
        })

        names = [c.function.name for c in tool_calls]
        logger.info("Iteration %d: model requested %d tools: %s", iteration, len(tool_calls), names)

        yield _TOOL_STATUS_LABELS.get(names[0], "Working…")

        has_verify = any(c.function.name == "verify_otp" for c in tool_calls)

        if len(tool_calls) == 1 or has_verify:
            for call in tool_calls:
                result = await _execute_tool(call, session_id)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.function.name,
                    "content": json.dumps(result),
                })
        else:
            results = await asyncio.gather(
                *(_execute_tool(c, session_id) for c in tool_calls)
            )
            for call, result in zip(tool_calls, results):
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.function.name,
                    "content": json.dumps(result),
                })
    logger.info("Tool loop total: %.3fs", time.perf_counter() - t_loop_start)


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
    t_request = time.perf_counter()
    try:
        t0 = time.perf_counter()
        nudge_contact = bool(session_id) and await should_nudge_for_contact(session_id)
        messages = await asyncio.to_thread(build_messages, chat_messages, session_id, nudge_contact)
        logger.info("build_messages took %.3fs (%d messages total)", time.perf_counter() - t0, len(messages))

        token_count = 0
        assistant_content = []
        async for event in _run_tool_loop(messages, session_id):
            if isinstance(event, tuple):
                _, delta = event
                if delta:
                    token_count += 1
                    assistant_content.append(delta)
                    yield _sse({"delta": delta, "done": False})
            else:
                yield _sse({"status": event, "done": False})

        # Save the turn to Redis session
        user_msg = next((m.content for m in reversed(chat_messages) if m.role == "user"), "")
        full_assistant_msg = "".join(assistant_content)
        if session_id:
            await save_turn(session_id, user_msg, full_assistant_msg)
            if await should_prompt_login(session_id):
                yield _sse({"prompt_login": True, "done": False})
                await mark_login_prompted(session_id)

        yield _sse({"delta": "", "done": True})
        logger.info("Request complete — %d delta chunks, total %.3fs", token_count, time.perf_counter() - t_request)
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Chat request failed after %.3fs", time.perf_counter() - t_request)
        err_msg = _error_message(exc)
        
        from app.notifier import send_critical_alert
        err_msg_lower = err_msg.lower()
        if "404" in err_msg_lower or "402" in err_msg_lower or "credit" in err_msg_lower:
            asyncio.create_task(send_critical_alert("llm_credits", err_msg, "Failed to stream chat response"))
        elif "429" in err_msg_lower or "rate limit" in err_msg_lower:
            asyncio.create_task(send_critical_alert("llm_rate_limit", err_msg, "Failed to stream chat response due to rate limits"))
        elif "500" in err_msg_lower or "502" in err_msg_lower or "503" in err_msg_lower or "529" in err_msg_lower or "overloaded" in err_msg_lower:
            asyncio.create_task(send_critical_alert("llm_outage", err_msg, "Upstream LLM provider returned 500+ error"))

        yield _sse({"delta": "", "done": True, "error": err_msg})
