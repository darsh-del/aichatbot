"""Per-session store for the bucketlistt authToken, so a logged-in user isn't
asked to re-verify an OTP on every turn.

The chat backend is otherwise stateless (the client resends the conversation
each turn), but tool-call results — including the authToken from verify_otp —
are NOT part of that resent history, so without this the token is lost between
turns and the model re-runs send_otp. Here we cache the token server-side keyed
by the client's session_id and reuse it until it expires.

ponytail: in-memory single-process dict with a TTL. Fine for one uvicorn worker
on the demo box. Move to Redis (same interface) if you run multiple workers or
need the token to survive a restart. The token is never sent to the client — it
lives only here and is injected into authenticated MCP calls server-side.
"""
import time

# session_id -> (authToken, expiry_epoch)
_store: dict[str, tuple[str, float]] = {}

TTL_SECONDS = 30 * 60  # bucketlistt sessions are short-lived; 30 min is safe.

# MCP tools that require an authToken argument.
AUTH_TOOLS = {"add_to_cart", "get_cart", "update_cart_item", "remove_from_cart", "get_my_bookings"}


def set_token(session_id: str | None, token: str | None) -> None:
    if session_id and token:
        _store[session_id] = (token, time.time() + TTL_SECONDS)


def get_token(session_id: str | None) -> str | None:
    if not session_id:
        return None
    entry = _store.get(session_id)
    if not entry:
        return None
    token, expiry = entry
    if time.time() > expiry:
        _store.pop(session_id, None)
        return None
    return token


def extract_token(result_text: str) -> str | None:
    """Pull an authToken out of a verify_otp tool result (shape may vary)."""
    import json

    try:
        data = json.loads(result_text)
    except (ValueError, TypeError):
        return None
    # Check the common locations: top-level or nested under data/result.
    for scope in (data, data.get("data") if isinstance(data, dict) else None,
                  data.get("result") if isinstance(data, dict) else None):
        if isinstance(scope, dict):
            tok = scope.get("authToken") or scope.get("token")
            if isinstance(tok, str) and tok:
                return tok
    return None
