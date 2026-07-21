"""Pydantic request/response models for the chat API.

Restricting `role` to "user"/"assistant" (no "system") means FastAPI's
normal request validation already rejects a client-supplied system message
with a 422 - no custom validator needed.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """A single message in the conversation, as sent by the client."""

    role: Literal["user", "assistant"]
    # 8000 chars ≈ 2000 tokens — plenty for a real question, blocks token-flood abuse.
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    """Request body for POST /api/chat."""

    # 40 messages ≈ 20 turns; anything longer is either a bug or abuse. The client
    # resends full history each turn, so capping this bounds the worst-case request size.
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    session_id: Optional[str] = None
