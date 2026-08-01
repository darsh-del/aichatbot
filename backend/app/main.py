"""FastAPI application entrypoint. Thin route handlers only - business
logic lives in app.llm / app.tools.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import settings
from app.llm import stream_chat_response
from app.mcp_client import close_persistent_session
from app.rate_limit import RateLimitMiddleware
from app.schemas import ChatRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting up — model=%s, MCP=%s, Weaviate=%s",
        settings.llm_model,
        bool(settings.mcp_server_url),
        bool(settings.weaviate_url),
    )
    yield
    logger.info("Shutting down — closing MCP session")
    await close_persistent_session()


app = FastAPI(title="Chatbot Backend", lifespan=lifespan)

app.add_middleware(RateLimitMiddleware)
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
    logger.info(
        "POST /api/chat — %d messages, session=%s",
        len(request.messages),
        request.session_id or "none",
    )
    return StreamingResponse(
        stream_chat_response(request.messages, request.session_id),
        media_type="text/event-stream",
    )
