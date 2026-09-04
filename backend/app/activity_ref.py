"""Small reference numbers standing in for catalog activity ids, so the raw
Mongo `_id` never has to reach the browser — not in the chat text, and not in
the `activity:<ref>` link's href either, where opening the browser's Inspect
panel could otherwise read it.

Why any reference is needed at all: the "more details" card (see
ActivityModal.tsx) works by the browser asking the server for one specific
activity after the user clicks it (GET /api/activity/{ref} in app/main.py).
For that round trip to work, SOME value identifying "which activity" has to
travel from the server to the browser and back — there's no way around a
client needing data to make its next request. What this module controls is
*what that value looks like*: a small opaque counter ("1", "2", "17", ...)
that carries no information about the real id, instead of the real 24-char
Mongo ObjectId itself.

Deliberately NOT encryption/encoding of the real id (an earlier version of
this file did that with XOR + base32) — just a plain lookup table, in both
directions, kept in memory:
  - id -> ref, so the same activity mentioned again (same turn, later turn,
    or a different user) reuses its existing ref instead of minting a new one
    every time.
  - ref -> id, to resolve a click back to the real id.

The LLM itself still sees and uses the real `_id` for its own tool calls
(get_time_slots, get_activity_addons, add_to_cart, ...) - none of that ever
reaches the browser, so there's nothing to hide there; only the copy that's
about to go out over SSE gets swapped (see app/stream_sanitizer.py).

ponytail: in-memory only, not Redis-backed - this backend runs as one process
(see backend/Dockerfile's plain `uvicorn`, no --workers), so a single shared
dict is enough for every request to see the same mapping, and the catalog
(a few hundred activities) makes this a non-issue memory-wise. It resets on
a redeploy: a "more details" link shown just before a restart would 404 until
the user asks again - a rare, low-severity cosmetic gap, not data loss (the
underlying activity is untouched; only the click-through number is stale).
Upgrade path if that ever matters: back the two dicts with Redis (already
used elsewhere in this app - see app/cache.py) instead of plain dicts.
"""
import re

_HEX24_RE = re.compile(r"^[a-fA-F0-9]{24}$")

_id_to_ref: dict[str, str] = {}
_ref_to_id: dict[str, str] = {}
_next_ref = 1


def get_or_create_ref(real_id: str) -> str:
    """Real Mongo `_id` -> its reference number, minting a new one on first sight.

    Raises ValueError if real_id doesn't look like a Mongo ObjectId at all -
    better to fail loudly than hand out a reference for garbage input.
    """
    global _next_ref
    if not _HEX24_RE.match(real_id):
        raise ValueError(f"not a 24-hex-char id: {real_id!r}")
    # Lower-cased before use as the dict key: a hex ObjectId is valid in either
    # case (the model has been seen emitting both for the same activity), and
    # the catalog's own ids are always lower-case anyway - without this, the
    # same activity referenced once in each case would mint two different
    # reference numbers for what a click on either one still correctly
    # resolves to the same record, just a wasted, confusing extra ref.
    real_id = real_id.lower()
    ref = _id_to_ref.get(real_id)
    if ref is None:
        ref = str(_next_ref)
        _next_ref += 1
        _id_to_ref[real_id] = ref
        _ref_to_id[ref] = real_id
    return ref


def resolve_ref(ref: str) -> str | None:
    """Reference number -> the real Mongo `_id`, or None if it's not one we handed out."""
    return _ref_to_id.get(ref)
