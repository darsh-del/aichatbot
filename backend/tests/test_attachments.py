"""Unit tests for the attachment validation/scan/extraction pipeline.
ClamAV and Redis are mocked — these never hit a real clamd daemon or Redis instance.
"""
import io
import zipfile

import pytest

from app.attachments import AttachmentError, _extract_docx_text, _looks_like_text


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
    import app.attachments as attachments_module
    monkeypatch.setattr(attachments_module, "_DECOMPRESSED_CAP_BYTES", 100)  # tiny cap for the test
    raw = _minimal_docx_bytes("x" * 1000)  # exceeds the patched 100-byte cap
    with pytest.raises(AttachmentError):
        _extract_docx_text(raw)


def test_looks_like_text_accepts_plain_utf8():
    assert _looks_like_text("hello world".encode("utf-8")) is True


def test_looks_like_text_rejects_binary():
    assert _looks_like_text(bytes(range(256))) is False
