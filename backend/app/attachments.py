"""Attachment upload pipeline: validate, scan, extract, store.

Storage split, deliberate: binary blobs (images, PDFs) go to local disk in a
TTL-swept temp directory, NOT Redis — Redis is shared with the session store
and MCP cache (see config.py's redis_url), and a burst of concurrent 10-32MB
uploads would compete with active chat sessions for the same memory budget.
Redis holds only small metadata plus the (genuinely tiny) extracted text for
docx/txt attachments. This app is explicitly single-process today (see the
comment in rate_limit.py) so local disk is a legitimate match for its current
deployment shape — revisit if this app is ever horizontally scaled.
"""
import io
import json
import logging
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

import clamd
import filetype
from defusedxml import ElementTree as SafeET
from docx import Document
from fastapi import UploadFile

from app.config import settings
from app.session_store import redis_client as _redis  # reuse the existing shared Redis client

logger = logging.getLogger(__name__)

_ALLOWED = {
    "image/jpeg": "image",
    "image/png": "image",
    "application/pdf": "pdf",
    "text/plain": "text",
    # docx's magic-byte signature is a plain zip; verified as an Office file
    # by internal structure in _extract_docx_text below, not by MIME sniff alone.
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}
_SIZE_CAPS_MB = {
    "image": lambda: settings.attachment_max_image_mb,
    "pdf": lambda: settings.attachment_max_pdf_mb,
    "docx": lambda: settings.attachment_max_docx_mb,
    "text": lambda: 2,
}
_DECOMPRESSED_CAP_BYTES = 50 * 1024 * 1024  # zip-bomb ceiling for docx extraction
_ATTACHMENT_TTL_SECONDS = 7200  # matches SESSION_TTL_SECONDS — attachments don't outlive the chat session


class AttachmentError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(message)


@dataclass
class StoredAttachment:
    attachment_id: str
    media_type: str  # "image" | "pdf" | "text" | "docx" (docx is stored as extracted text)
    filename: str
    size_bytes: int


@dataclass
class ResolvedAttachment:
    media_type: str
    mime_type: str
    filename: str
    # exactly one of these is populated, depending on media_type
    text: str | None = None
    disk_path: str | None = None

    def to_content_block(self) -> dict:
        if self.media_type == "text" or self.media_type == "docx":
            return {"type": "text", "text": f"[Attached file: {self.filename}]\n{self.text}"}
        raw = Path(self.disk_path).read_bytes()
        import base64
        b64 = base64.b64encode(raw).decode()
        if self.media_type == "image":
            return {
                "type": "image_url",
                "image_url": {"url": f"data:{self.mime_type};base64,{b64}"},
            }
        return {  # pdf
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": self.mime_type,
                "data": b64
            }
        }


def _clamd_client() -> "clamd.ClamdNetworkSocket":
    return clamd.ClamdNetworkSocket(host=settings.clamd_host, port=settings.clamd_port)


def _scan_or_raise(raw: bytes) -> None:
    """Malware scan before anything else touches the bytes. Fail closed: if
    clamd itself is unreachable, reject the upload rather than silently
    skipping the scan — this is a security control, not a best-effort cache.
    """
    try:
        result = _clamd_client().instream(io.BytesIO(raw))
    except Exception as exc:
        logger.error("ClamAV scan unavailable: %s", exc)
        raise AttachmentError(503, "Attachment scanning is temporarily unavailable — try again shortly.")
    status, signature = result.get("stream", (None, None))
    if status == "FOUND":
        logger.warning("Malware detected in upload: %s", signature)
        raise AttachmentError(422, "This file failed a security scan and can't be uploaded.")


def _extract_docx_text(raw: bytes) -> str:
    """Extract text from a .docx, hardened against its two named vulnerability
    classes (both are historical CVEs in the naive approach, not hypothetical):

    - XXE (CVE-2016-5851 in python-docx, fixed 0.8.6+): parse with defusedxml
      instead of trusting whatever XML stack python-docx uses internally, in
      case a docx smuggles an external-entity declaration.
    - Zip/decompression bomb: a docx is a zip of XML; a small file can expand
      to gigabytes. Check each entry's declared uncompressed size against a
      hard ceiling BEFORE extracting, not after.
    """
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        total = 0
        for info in zf.infolist():
            total += info.file_size
            if total > _DECOMPRESSED_CAP_BYTES:
                raise AttachmentError(422, "This document is too large to process.")
        try:
            xml_bytes = zf.read("word/document.xml")
        except KeyError:
            raise AttachmentError(422, "This doesn't look like a valid Word document.")

    # Parse with defusedxml (external entities disabled by default) rather
    # than handing raw XML to python-docx's own parser.
    SafeET.fromstring(xml_bytes)  # raises on any XXE attempt; discard result, just validating

    # Now safe to let python-docx do the actual structured extraction.
    doc = Document(io.BytesIO(raw))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


async def store_attachment(file: UploadFile) -> StoredAttachment:
    raw = await file.read()
    kind = filetype.guess(raw)
    mime = kind.mime if kind else (file.content_type or "")

    # Magic-byte check for everything except docx/txt, whose real "type" is
    # verified structurally instead (a zip signature alone doesn't prove it's
    # a valid docx — _extract_docx_text does the real verification).
    is_txt = mime in ("text/plain", "") and _looks_like_text(raw)
    is_docx = mime == "application/zip" and (file.filename or "").lower().endswith(".docx")
    if not is_txt and not is_docx and mime not in _ALLOWED:
        raise AttachmentError(415, "Unsupported file type. Allowed: jpg, png, pdf, txt, docx.")

    media_type = "text" if is_txt else "docx" if is_docx else _ALLOWED[mime]
    cap_mb = _SIZE_CAPS_MB[media_type]()
    if len(raw) > cap_mb * 1024 * 1024:
        raise AttachmentError(413, f"File too large — {media_type} attachments are capped at {cap_mb}MB.")

    _scan_or_raise(raw)  # malware scan BEFORE any parsing, on every type

    attachment_id = uuid.uuid4().hex
    filename = file.filename or "attachment"

    if media_type in ("text", "docx"):
        text = raw.decode("utf-8", errors="replace") if media_type == "text" else _extract_docx_text(raw)
        await _redis.set(
            f"attachment:{attachment_id}",
            json.dumps({"media_type": media_type, "filename": filename, "text": text}),
            ex=_ATTACHMENT_TTL_SECONDS,
        )
    else:
        Path(settings.attachments_dir).mkdir(parents=True, exist_ok=True)
        disk_path = Path(settings.attachments_dir) / attachment_id
        disk_path.write_bytes(raw)
        await _redis.set(
            f"attachment:{attachment_id}",
            json.dumps({
                "media_type": media_type, "filename": filename,
                "disk_path": str(disk_path), "mime_type": mime,
                "stored_at": time.time(),
            }),
            ex=_ATTACHMENT_TTL_SECONDS,
        )

    return StoredAttachment(attachment_id, media_type, filename, len(raw))


async def resolve_attachment(attachment_id: str) -> ResolvedAttachment | None:
    raw = await _redis.get(f"attachment:{attachment_id}")
    if raw is None:
        return None  # expired or never existed — caller degrades gracefully
    meta = json.loads(raw)
    return ResolvedAttachment(
        media_type=meta["media_type"],
        mime_type=meta.get("mime_type", "text/plain"),
        filename=meta["filename"],
        text=meta.get("text"),
        disk_path=meta.get("disk_path"),
    )


def _looks_like_text(raw: bytes) -> bool:
    try:
        raw[:4096].decode("utf-8")
        return b"\x00" not in raw[:4096]
    except UnicodeDecodeError:
        return False
