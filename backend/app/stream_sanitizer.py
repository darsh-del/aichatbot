"""Streaming-safe cleanup of assistant output before it reaches the client.

Two jobs, one buffer, because both need the same fix for the same reason:
  1. Strip em/en dash glyphs the model may still emit despite the prompt rule (§1.1).
  2. Strip any raw Mongo ObjectId the model might mention (§2.1) — activities are
     referenced by name only now (no more `activity:<id>` links - that whole
     click-to-detail feature was removed), so there's no legitimate reason for a
     24-hex-char id to ever appear in a reply. Always strip it, no exceptions.

     The id is matched case-insensitively (`[a-fA-F0-9]`): a hex ObjectId is valid
     in either case, and the model has been observed emitting one in upper case -
     e.g. "(ACTIVITY:69B90FEFB32379387CBAAC66)" - which a lowercase-only pattern
     would miss entirely and leak straight through.

     The boundary check is spelled out as "not glued to more ASCII alnum" instead
     of `\\b`: Python's `\\b` is Unicode-aware, and a Devanagari (or other Indic-
     script) letter IS a word char to it. This app must reply in 26 Indian
     languages (knowledge_base.md's "Language: mirror the user" rule) and the
     model doesn't reliably put an ASCII space between an id and script text right
     next to it - "...66f1a2b3c4d5e6f7a8b9c0d1देखें" has NO `\\b` between the id
     and "देखें" at all, so `\\b[a-f0-9]{24}\\b` would silently fail to match. What
     actually matters is only that the id isn't glued to MORE Latin letters/digits
     (which would mean it's not really a clean 24-char token) - so anchor on that
     specifically, in either script.

ponytail: the boundary check still can't see an id glued to MORE Latin/digit
characters on either side with zero separator (e.g. two ids concatenated
back-to-back, or "id66f1a2b3c4d5e6f7a8b9c0d1x") - there's no boundary-based way
to isolate a 24-char run inside a longer unbroken alnum run without risking
false positives on real content. Not observed in practice (every leak seen so
far has the id isolated by at least punctuation/space/non-Latin-script), so not
chased further. Upgrade path if it ever is: match runs of >=24 hex chars and
warn loudly rather than silently mis-stripping a legitimate longer alnum token.

Job 2 needs a tail buffer: `delta.content` arrives from the provider stream in
small, arbitrary-sized pieces, so a 24-char ObjectId routinely lands split across
two or more chunks. A per-chunk regex would simply never see the whole id to
match against. Job 1 doesn't strictly need buffering (a single Python str
character can't itself be split across chunks) but runs through the same buffer
for one code path.

This only touches what's sent to the client over SSE — the raw, unmodified text
is still what's kept for the assistant's own conversation history (see call site
in llm.py::stream_chat_response) and for the Redis session transcript, since the
model needs its own tool-call ids to keep reasoning correctly turn to turn.
Sanitization is a presentation-layer concern; it must never alter what the model
itself "said" in the conversation it continues to reason over.
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

_NOT_ALNUM = r"[A-Za-z0-9]"
_RAW_OBJECTID_RE = re.compile(rf"(?<!{_NOT_ALNUM})[a-fA-F0-9]{{24}}(?!{_NOT_ALNUM})")


class StreamSanitizer:
    """Buffers streamed text so a pattern that spans multiple chunks isn't missed."""

    _TAIL = 24  # length of the longest pattern matched (a raw Mongo ObjectId)

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
            # This firing at all means the model mentioned a raw database id -
            # not secret, just noise the KB tells it never to show.
            logger.warning("StreamSanitizer stripped %d raw activity id(s) from output", hits)
        if len(self._buf) <= self._TAIL:
            return ""
        safe, self._buf = self._buf[: -self._TAIL], self._buf[-self._TAIL :]
        return safe

    def flush(self) -> str:
        """Call once when the stream ends to release the held-back tail."""
        rest, hits = _RAW_OBJECTID_RE.subn("", self._buf)
        if hits:
            logger.warning("StreamSanitizer stripped %d raw activity id(s) from output", hits)
        self._buf = ""
        return rest
