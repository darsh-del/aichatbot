"""Streaming-safe cleanup of assistant output before it reaches the client.

Two jobs, one buffer, because both need the same fix for the same reason:
  1. Strip em/en dash glyphs the model may still emit despite the prompt rule (§1.1).
  2. Strip a raw Mongo ObjectId that should have been wrapped in a real
     `[Name](activity:<id>)` link but wasn't (§2.1) — a model-formatting miss, not by
     design. The exclusion for "already inside a real link" checks for the actual
     link-open syntax `](activity:`, not just the bare word `activity:` — a model that
     writes the id as loose prose ("see activity:<id> for more") isn't real markdown
     link syntax either way, so it wouldn't render as a link — only the earlier,
     looser check let it through unstripped, which is what leaked the raw id to users.

Job 2 needs a tail buffer: `delta.content` arrives from the provider stream in small,
arbitrary-sized pieces, so a 24-char ObjectId routinely lands split across two or more
chunks. A per-chunk regex would simply never see the whole token to match against.
Job 1 doesn't strictly need buffering (a single Python str character can't itself be
split across chunks) but runs through the same buffer for one code path.

This only touches what's sent to the client over SSE — the raw, unmodified text is
still what's kept for the assistant's own conversation history (see call site in
llm.py::stream_chat_response) and for the Redis session transcript. Sanitization is a
presentation-layer concern; it must never alter what the model itself "said" in the
conversation it continues to reason over.
"""
import logging
import re

logger = logging.getLogger(__name__)

# Em dash -> comma (its usual job as a clause separator). En dash -> hyphen,
# NOT comma — an en dash is very often a numeric range in this KB's own
# content ("20-130 kg", "500-1,000 jumps", "October-June"); mapping it to a
# comma would turn "20-130 kg" into "20,130 kg", which reads as a different
# number entirely. Neither touches ASCII "-"/"--", which this app's own
# markdown tables rely on (see the comparison-table `|---|---|` syntax).
_DASH_MAP = str.maketrans({"—": ",", "–": "-"})
_LINK_OPEN = "](activity:"  # the actual markdown link-open syntax, not just the bare word
_RAW_OBJECTID_RE = re.compile(r"(?<!\]\(activity:)\b[a-f0-9]{24}\b")
# Same 24-hex shape, but with no lookbehind: used only to find ids that SURVIVED the
# strip above (i.e. legitimate, kept ones) so feed() can avoid ever slicing between
# such an id and its `](activity:` prefix - see the comment in feed() below.
_ANY_HEX24_RE = re.compile(r"\b[a-f0-9]{24}\b")


class StreamSanitizer:
    """Buffers streamed text so a pattern that spans multiple chunks isn't missed."""

    # Longest pattern matched: the link-open prefix plus a full ObjectId. Needs to
    # cover both, not just the id, so a `](activity:` that lands in one chunk and the
    # id in the next are still seen together before either gets sliced off as "safe".
    _TAIL = len(_LINK_OPEN) + 24

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, text: str) -> str:
        """Add newly streamed text; return the portion now safe to send to the client.

        The ObjectId regex runs against the WHOLE buffer before any slicing —
        not just the portion about to be released. Running it only on the
        release slice (an earlier version of this method did that) misses an
        ID that straddles the release/retain boundary: half of it goes out
        in this call's release, the other half sits in the retained tail,
        and neither half alone is 24 hex chars, so neither ever matches.
        Substituting first, then slicing, guarantees any complete match is
        caught while it's still whole in one buffer.
        """
        self._buf += text.translate(_DASH_MAP)
        self._buf, hits = _RAW_OBJECTID_RE.subn("", self._buf)
        if hits:
            # This firing at all means the model missed the `[Name](activity:<id>)`
            # format the prompt mandates - the backstop caught it instead of the id
            # reaching the user raw. Not the id itself: it's not secret, just noise.
            logger.warning("StreamSanitizer stripped %d raw activity id(s) from output", hits)
        if len(self._buf) <= self._TAIL:
            return ""
        cut = len(self._buf) - self._TAIL

        # Any 24-hex blob still in the buffer at this point survived the strip above,
        # so it's a real, already-verified `[Name](activity:<id>)` id - never split
        # from its `](activity:` prefix by pushing `cut` through, or just past, it.
        # A later feed()/flush() call re-runs the same strip regex on whatever's
        # retained; if that call no longer has the full prefix in view (because an
        # earlier cut released it separately from the id), the lookbehind fails and
        # a perfectly valid link's id gets wrongly stripped out from under it - the
        # bug worst-case (one-char-at-a-time) streaming exposed during testing.
        for m in _ANY_HEX24_RE.finditer(self._buf):
            if m.start() - len(_LINK_OPEN) < cut <= m.end():
                cut = m.start() - len(_LINK_OPEN)
        cut = max(cut, 0)

        safe, self._buf = self._buf[:cut], self._buf[cut:]
        return safe

    def flush(self) -> str:
        """Call once when the stream ends to release the held-back tail.

        Deliberately does NOT re-run the objectid regex here. `feed()` already
        substitutes over the full buffer (old tail + new text) on every call, so by
        the time flush() runs, whatever's left has already been resolved against the
        fullest context that will ever exist for it. Re-matching against just the
        retained tail is not only redundant, it's actively wrong: a lookbehind that
        was satisfied when the full buffer was in view (e.g. `](activity:` sitting
        just before the id) can fail once slicing has pushed that prefix out into the
        already-released `safe` portion, silently flipping a correctly-preserved
        activity link's id into a stripped one on the last few characters of a reply.
        """
        rest = self._buf
        self._buf = ""
        return rest
