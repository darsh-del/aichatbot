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
import json
from pathlib import Path
from typing import AsyncGenerator

import litellm

from app.config import settings
from app.mcp_client import ALLOWED_TOOLS as MCP_ALLOWED_TOOLS
from app.mcp_client import call_catalog_tool, load_catalog_tools, mcp_session
from app.retriever import retrieve
from app.schemas import ChatMessage
from app.tools import TOOL_SCHEMAS, dispatch_tool

# ponytail: fixed cap on tool-call round trips rather than unbounded looping -
# guards against a model that never stops requesting tools. Raise if a real
# workflow legitimately needs a longer tool chain.
MAX_TOOL_ITERATIONS = 5

# Bounds worst-case cost per turn — a normal answer is well under this.
MAX_OUTPUT_TOKENS = 1500


def _load_base_prompt() -> str:
    """Read the base system-prompt / knowledge-base file configured via SYSTEM_PROMPT_FILE."""
    return Path(settings.system_prompt_file).read_text(encoding="utf-8")


def build_messages(chat_messages: list[ChatMessage]) -> list[dict]:
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
            "Use the following retrieved information to answer the user's question accurately.\n\n"
            f"{rag_context}"
        )
    else:
        system_content = base_prompt

    if settings.mcp_server_url:
        system_content += (
            "\n\n## Live Catalog Tools\n"
            "You also have live, read-only catalog tools (get_destinations, get_experiences, "
            "get_activities, get_activity, search_activities_by_destination_and_tag, "
            "get_activity_slots, get_activity_addons) that query bucketlistt's real database. "
            "Prefer calling these over guessing whenever a user asks about a destination, activity, "
            "price, or availability that isn't already covered above, or whenever they ask for "
            "current/live/real-time information - never invent destinations, activities, prices, "
            "or slots. These tools are read-only: you cannot log a user in, touch a cart, or take "
            "payment, so for booking or payment requests use escalate_and_capture_lead or point the "
            "user to the website/app instead."
        )

    system_message = {"role": "system", "content": system_content}
    return [system_message] + [m.model_dump() for m in chat_messages]


async def _run_tool_loop(messages: list[dict]) -> list[dict]:
    """Call the model, executing any requested tool calls, until it stops
    asking for tools (or MAX_TOOL_ITERATIONS is hit).

    Tools come from two sources: the local TOOL_SCHEMAS (escalate_and_capture_lead)
    and, if MCP_SERVER_URL is configured, the bucketlistt MCP server's read-only
    catalog tools (live destinations/activities/slots). Identity, cart, and payment
    MCP tools are never loaded - see app/mcp_client.py.

    Returns the accumulated message history, ready for a final streamed call.
    """
    async with mcp_session() as session:
        tools = TOOL_SCHEMAS + await load_catalog_tools(session)
        for _ in range(MAX_TOOL_ITERATIONS):
            response = await litellm.acompletion(
                model=settings.llm_model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                max_tokens=MAX_OUTPUT_TOKENS,
            )
            message = response.choices[0].message
            tool_calls = getattr(message, "tool_calls", None)
            if not tool_calls:
                break
            messages.append(message.model_dump())
            for call in tool_calls:
                if call.function.name in MCP_ALLOWED_TOOLS:
                    result = await call_catalog_tool(session, call)
                else:
                    result = dispatch_tool(call.function.name, call.function.arguments)
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


async def stream_chat_response(chat_messages: list[ChatMessage]) -> AsyncGenerator[str, None]:
    """Run the tool loop then stream the final answer as SSE frames.

    Always ends with a `done: true` frame - on any failure, that frame
    carries an `error` field instead of the generator raising, so the
    client-side stream never just drops.
    """
    try:
        messages = build_messages(chat_messages)
        messages = await _run_tool_loop(messages)
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
