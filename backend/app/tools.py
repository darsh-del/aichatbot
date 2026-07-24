"""Local tools exposed to the LLM via function/tool calling.

- `escalate_and_capture_lead`: Capture high-value group booking leads or human agent requests,
  saving them to backend/data/leads.json and generating an escalation ticket reference.
- `search_web`: Fresh web-search fallback via OpenAI's gpt-4o-mini-search-preview. Used only
  when the KB and MCP catalog don't have an answer (e.g. current season status, weather,
  time-sensitive info). Adds ~$0.025 per invocation, so the system prompt tells the model
  to reach for it sparingly.

Live catalog/availability data (destinations, activities, real-time slots) comes from the
bucketlistt MCP server instead — see app/mcp_client.py. That client is deliberately
restricted to read-only tools; identity, cart, and payment tools are never loaded, so this
chatbot has no way to log a user in, touch a cart, or move money.
"""
import inspect
import json
import random
import time
from pathlib import Path

import litellm

LEADS_FILE = Path(__file__).parent.parent / "data" / "leads.json"


def _ensure_leads_file() -> None:
    """Ensure data/leads.json exists."""
    if not LEADS_FILE.exists():
        LEADS_FILE.parent.mkdir(parents=True, exist_ok=True)
        LEADS_FILE.write_text("[]", encoding="utf-8")


def escalate_and_capture_lead(
    name: str = "",
    phone: str = "",
    email: str = "",
    group_size: int = 1,
    activity_interest: str = "",
    preferred_date: str = "",
    notes: str = "",
    urgency: str = "normal",
) -> dict:
    """Capture a lead or human agent request and generate an escalation ticket."""
    _ensure_leads_file()

    ticket_id = f"LEAD-{random.randint(10000, 99999)}"
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    lead_record = {
        "ticket_id": ticket_id,
        "timestamp": timestamp,
        "name": name or "Guest",
        "phone": phone,
        "email": email,
        "group_size": group_size,
        "activity_interest": activity_interest,
        "preferred_date": preferred_date,
        "notes": notes,
        "urgency": urgency,
        "status": "PENDING_HUMAN_CALLBACK",
    }

    try:
        data = json.loads(LEADS_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = []

    data.append(lead_record)
    LEADS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

    return {
        "status": "success",
        "ticket_id": ticket_id,
        "message": (
            f"Escalation lead captured successfully. Ticket #{ticket_id} created. "
            f"Human team will contact {name or 'Guest'} at {phone or 'the provided contact'} shortly."
        ),
        "lead_details": lead_record,
    }


async def search_web(query: str) -> dict:
    """Ask OpenAI's search-preview model to answer a query with fresh web info."""
    try:
        response = await litellm.acompletion(
            model="openai/gpt-4o-mini-search-preview",
            messages=[{"role": "user", "content": query}],
            web_search_options={"search_context_size": "low"},
        )
        return {"result": response.choices[0].message.content or ""}
    except Exception as exc:  # pylint: disable=broad-except
        return {"error": f"web search failed: {exc}"}


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": (
                "Search the live web for time-sensitive info that is not in your knowledge "
                "base or the Bucketlistt catalog tools — e.g. current season/monsoon status, "
                "weather at a destination, recent news about a location, or facts that may "
                "have changed. Only use this when the KB and catalog tools genuinely don't "
                "have the answer. Do NOT use for questions the KB already covers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Focused search query, e.g. 'Rishikesh river rafting season status 2026'.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_and_capture_lead",
            "description": (
                "Capture high-value group booking leads (5+ people), bulk discount inquiries, "
                "custom itinerary requests, or explicit customer requests to talk to a human agent. "
                "Generates an escalation ticket."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Customer's name if provided.",
                    },
                    "phone": {
                        "type": "string",
                        "description": "Customer's phone or WhatsApp number for human callback.",
                    },
                    "email": {
                        "type": "string",
                        "description": "Customer's email address if provided.",
                    },
                    "group_size": {
                        "type": "integer",
                        "description": "Number of people in the travel group (default 1).",
                    },
                    "activity_interest": {
                        "type": "string",
                        "description": "Activities or packages the group is interested in (e.g. '16km Rafting + Bungee for 12 people').",
                    },
                    "preferred_date": {
                        "type": "string",
                        "description": "Target date or month for the trip.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Summary of custom requirements, budget, or question for human team.",
                    },
                    "urgency": {
                        "type": "string",
                        "enum": ["normal", "medium", "high"],
                        "description": "Urgency level based on group size or explicit callback request.",
                    },
                },
                "required": [],
            },
        },
    },
]


_TOOL_REGISTRY = {
    "escalate_and_capture_lead": escalate_and_capture_lead,
    "search_web": search_web,
}


async def dispatch_tool(name: str, arguments: str) -> dict:
    """Execute a tool call by name, given its JSON-encoded arguments string."""
    func = _TOOL_REGISTRY.get(name)
    if func is None:
        return {"error": f"unknown tool: {name}"}
    kwargs = json.loads(arguments) if arguments else {}
    result = func(**kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result
