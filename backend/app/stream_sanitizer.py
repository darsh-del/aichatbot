"""Streaming-safe cleanup of assistant output before it reaches the client.

Two jobs, one buffer, because both need the same fix for the same reason:
  1. Strip em/en dash glyphs the model may still emit despite the prompt rule (§1.1).
  2. Strip a raw Mongo ObjectId that should have been wrapped in an `activity:` link
     but wasn't (§2.1) — a model-formatting miss, not by design.

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
import re

_DASH_MAP = str.maketrans({"—": ",", "–": ","})  # em/en dash only — never touch ASCII "-" or "--",
                                                   # which this app's own markdown tables rely on
                                                   # (see the comparison-table `|---|---|` syntax).
_RAW_OBJECTID_RE = re.compile(r"(?<!activity:)\b[a-f0-9]{24}\b")


class StreamSanitizer:
    """Buffers streamed text so a pattern that spans multiple chunks isn't missed."""

    _TAIL = 24  # length of the longest pattern matched (a raw Mongo ObjectId)

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, text: str) -> str:
        """Add newly streamed text; return the portion now safe to send to the client."""
        self._buf += text.translate(_DASH_MAP)
        if len(self._buf) <= self._TAIL:
            return ""
        safe, self._buf = self._buf[: -self._TAIL], self._buf[-self._TAIL :]
        return _RAW_OBJECTID_RE.sub("", safe)

    def flush(self) -> str:
        """Call once when the stream ends to release the held-back tail."""
        rest = _RAW_OBJECTID_RE.sub("", self._buf)
        self._buf = ""
        return rest
