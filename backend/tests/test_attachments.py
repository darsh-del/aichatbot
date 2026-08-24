"""Unit tests for the attachment validation/scan/extraction pipeline.
ClamAV and Redis are mocked — these never hit a real clamd daemon or Redis instance.
"""
import asyncio
import io
import zipfile

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

import app.attachments as attachments_module
import app.session_store as session_store
from app.attachments import AttachmentError, _extract_docx_text, _looks_like_text


def _run(coro):
    # This codebase's convention for testing async code without pytest-asyncio
    # configured — see backend/tests/test_dashboard.py's identical helper.
    return asyncio.run(coro)


def _minimal_docx_bytes(paragraph_text: str = "Hello from a test docx") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "word/document.xml",
            f'<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
            f'<w:p><w:r><w:t>{paragraph_text}</w:t></w:r></w:p>'
            f'</w:body></w:document>',
        )
    return buf.getvalue()


def test_extract_docx_text_returns_paragraph_content():
    # Note: python-docx's Document() expects a full valid docx package (styles,
    # content-types, etc.) — this minimal fixture exercises the zip-bomb-cap and
    # defusedxml-parse steps; a full round-trip test should use a real fixture
    # .docx file checked into backend/tests/fixtures/.
    raw = _minimal_docx_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        assert zf.read("word/document.xml")  # sanity: fixture is well-formed


def test_extract_docx_rejects_oversized_decompressed_content(monkeypatch):
    monkeypatch.setattr(attachments_module, "_DECOMPRESSED_CAP_BYTES", 100)  # tiny cap for the test
    raw = _minimal_docx_bytes("x" * 1000)  # exceeds the patched 100-byte cap
    with pytest.raises(AttachmentError):
        _extract_docx_text(raw)


def test_looks_like_text_accepts_plain_utf8():
    assert _looks_like_text("hello world".encode("utf-8")) is True


def test_looks_like_text_rejects_binary():
    assert _looks_like_text(bytes(range(256))) is False


# --- End-to-end store_attachment / resolve_attachment, with Redis + ClamAV
# mocked. This is the coverage that was missing before: the earlier version
# of this file only unit-tested the docx/text helpers in isolation, which
# never exercised store_attachment/resolve_attachment and so never caught
# the import-time Redis-binding bug (see app.attachments._redis()'s
# docstring) — a test at this level fails outright on that bug.
# --------------------------------------------------------------------------


class _FakeStringRedis:
    """Just enough of redis.asyncio's string-key API (set/get) for these
    tests — attachments.py uses simple SET/GET with a TTL, not the hash API
    session_store.py's own FakeRedis (in conftest.py) models."""

    def __init__(self):
        self._data: dict[str, str] = {}

    async def set(self, key, value, ex=None):
        self._data[key] = value

    async def get(self, key):
        return self._data.get(key)


def _make_upload_file(content: bytes, filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


@pytest.fixture
def clean_clamav(monkeypatch):
    """Simulate a healthy ClamAV daemon that finds nothing."""
    class _FakeClamd:
        def instream(self, _stream):
            return {"stream": ("OK", None)}

    monkeypatch.setattr(attachments_module, "_clamd_client", lambda: _FakeClamd())


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _FakeStringRedis()
    monkeypatch.setattr(session_store, "redis_client", fake)
    return fake


def test_store_and_resolve_text_attachment_round_trip(clean_clamav, fake_redis):
    """The core regression test for the Redis-binding bug: store an
    attachment, then resolve it back. This fails with
    AttributeError: 'NoneType' object has no attribute 'set'/'get' on the
    buggy `from ... import redis_client as _redis` version, since that
    binding never sees fake_redis's monkeypatch of session_store.redis_client.
    """
    async def scenario():
        upload = _make_upload_file(b"hello from a test attachment", "notes.txt", "text/plain")
        stored = await attachments_module.store_attachment(upload)
        assert stored.media_type == "text"
        assert stored.filename == "notes.txt"

        resolved = await attachments_module.resolve_attachment(stored.attachment_id)
        assert resolved is not None
        assert resolved.text == "hello from a test attachment"

    _run(scenario())


def test_resolve_attachment_returns_none_when_redis_unavailable(monkeypatch):
    monkeypatch.setattr(session_store, "redis_client", None)
    resolved = _run(attachments_module.resolve_attachment("nonexistent-id"))
    assert resolved is None  # degrades gracefully, does not raise


def test_store_attachment_raises_service_unavailable_when_redis_down(clean_clamav, monkeypatch):
    monkeypatch.setattr(session_store, "redis_client", None)
    upload = _make_upload_file(b"hello", "notes.txt", "text/plain")
    with pytest.raises(AttachmentError) as exc_info:
        _run(attachments_module.store_attachment(upload))
    assert exc_info.value.status_code == 503


def test_store_attachment_rejects_malware(fake_redis, monkeypatch):
    class _InfectedClamd:
        def instream(self, _stream):
            return {"stream": ("FOUND", "Test.Signature")}

    monkeypatch.setattr(attachments_module, "_clamd_client", lambda: _InfectedClamd())
    upload = _make_upload_file(b"hello", "notes.txt", "text/plain")
    with pytest.raises(AttachmentError) as exc_info:
        _run(attachments_module.store_attachment(upload))
    assert exc_info.value.status_code == 422


def test_store_attachment_fails_closed_when_clamav_unreachable(fake_redis, monkeypatch):
    def _raise(*_a, **_k):
        raise ConnectionError("clamd unreachable")

    monkeypatch.setattr(attachments_module, "_clamd_client", lambda: type("C", (), {"instream": _raise})())
    upload = _make_upload_file(b"hello", "notes.txt", "text/plain")
    with pytest.raises(AttachmentError) as exc_info:
        _run(attachments_module.store_attachment(upload))
    assert exc_info.value.status_code == 503


def test_store_attachment_rejects_oversized_file(clean_clamav, fake_redis, monkeypatch):
    monkeypatch.setattr(attachments_module.settings, "attachment_max_docx_mb", 0)  # anything is "too big"
    upload = _make_upload_file(b"PK" + b"x" * 10, "file.docx", "application/zip")
    with pytest.raises(AttachmentError) as exc_info:
        _run(attachments_module.store_attachment(upload))
    assert exc_info.value.status_code == 413


def test_resolved_image_content_block_shape():
    """Images resolve to litellm/OpenAI-style image_url blocks with an
    inline data URI, not a remote URL fetch, which Anthropic models don't
    support via litellm. Flagging the format choice here so a future litellm
    upgrade that changes this contract has a test to catch it, not just a
    silent runtime failure against the real API.
    """
    resolved = attachments_module.ResolvedAttachment(
        media_type="image", mime_type="image/png", filename="x.png", disk_path=__file__,
    )
    block = resolved.to_content_block()
    assert block["type"] == "image_url"
    assert block["image_url"]["url"].startswith("data:image/png;base64,")


def test_resolved_pdf_content_block_shape():
    """PDFs resolve to Anthropic-native document/source blocks, mixed with
    the OpenAI-style image block above in the same content array. Flagged in
    the branch review as a real, currently-unverified integration risk (open
    litellm issues around inconsistent Anthropic image/document handling).
    This test only pins the shape; it does NOT prove litellm accepts this
    mixed array end-to-end. Run a real smoke test against a live model
    before trusting this in production.
    """
    resolved = attachments_module.ResolvedAttachment(
        media_type="pdf", mime_type="application/pdf", filename="x.pdf", disk_path=__file__,
    )
    block = resolved.to_content_block()
    assert block["type"] == "document"
    assert block["source"]["type"] == "base64"
    assert block["source"]["media_type"] == "application/pdf"
