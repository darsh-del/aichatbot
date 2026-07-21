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
    content: str


class ChatRequest(BaseModel):
    """Request body for POST /api/chat."""

    messages: list[ChatMessage] = Field(min_length=1)
    session_id: Optional[str] = None
