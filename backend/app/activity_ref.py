"""Reversible obfuscation for catalog activity ids shown to the browser.

The LLM still sees and uses the real Mongo `_id` for its own tool calls
(get_time_slots, get_activity_addons, add_to_cart, ...) — none of that ever
reaches the browser, so there's nothing to hide there. The only place a real
id would otherwise reach the client is the `[Name](activity:<_id>)` link's
href, which the "more details" card round-trips back to the server via
GET /api/activity/{id} (see app/main.py). StreamSanitizer swaps the real id
for its token right before that link goes out over SSE (see
_replace_kept_id in app/stream_sanitizer.py); this module does the swap in
both directions.

Deterministic and stateless on purpose — no store, no TTL, no Redis
dependency to keep in sync: the same id always obfuscates to the same
token, and the token always recovers the same id, with the live catalog
(app/mcp_client.py) as the only source of truth either way. This is about
keeping the raw database id *shape* out of the DOM/Inspect, not encryption —
the activity/product an id points to is already public on bucketlistt.com's
own pages, so there's no sensitive data being protected here, just hygiene.
"""
import base64
import binascii
import hashlib

from app.config import settings

_ID_BYTES = 12  # a Mongo ObjectId is 12 raw bytes (24 hex chars)


def _keystream() -> bytes:
    return hashlib.sha256(settings.activity_id_key.encode()).digest()[:_ID_BYTES]


def obfuscate_activity_id(hex_id: str) -> str:
    """24-hex-char id -> opaque token. Raises ValueError if hex_id isn't one."""
    raw = bytes.fromhex(hex_id)
    if len(raw) != _ID_BYTES:
        raise ValueError(f"not a {_ID_BYTES}-byte id: {hex_id!r}")
    xored = bytes(b ^ k for b, k in zip(raw, _keystream()))
    return base64.b32encode(xored).decode("ascii").rstrip("=").lower()


def deobfuscate_activity_id(token: str) -> str | None:
    """Opaque token -> the original 24-hex-char id, or None if token is invalid."""
    try:
        padded = token.upper() + "=" * (-len(token) % 8)
        xored = base64.b32decode(padded)
    except (ValueError, binascii.Error):
        return None
    if len(xored) != _ID_BYTES:
        return None
    return bytes(b ^ k for b, k in zip(xored, _keystream())).hex()
