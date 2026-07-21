"""FastAPI application entrypoint. Thin route handlers only - business
logic lives in app.llm / app.tools.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import settings
from app.llm import stream_chat_response
from app.schemas import ChatRequest

app = FastAPI(title="Chatbot Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict:
    """Liveness/readiness probe reporting the currently configured model."""
    return {"status": "ok", "model": settings.llm_model}


@app.post("/api/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """Stream a chat completion as Server-Sent Events."""
    return StreamingResponse(
        stream_chat_response(request.messages),
        media_type="text/event-stream",
    )
