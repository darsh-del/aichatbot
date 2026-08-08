"""FastAPI application entrypoint. Thin route handlers only - business
logic lives in app.llm / app.tools.
"""
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.config import settings
from app.llm import stream_chat_response
from app.rate_limit import RateLimitMiddleware
from app.schemas import ChatRequest, UserInfoRequest
from app.session_store import init_redis, close_redis, save_user_info

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
    await init_redis()
    yield
    await close_redis()
    logger.info("Shutting down")


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
async def chat(request: ChatRequest, http_request: Request) -> StreamingResponse:
    """Stream a chat completion as Server-Sent Events.

    session_id resolution: an explicit value in the request body wins (a
    frontend that manages its own), else an existing session_id cookie,
    else a freshly generated one — set as a cookie on the response so a
    frontend that does nothing special still gets a stable session across
    requests, with no client-side UUID generation required.
    """
    session_id = request.session_id or http_request.cookies.get("session_id") or str(uuid.uuid4())
    logger.info(
        "POST /api/chat — %d messages, session=%s",
        len(request.messages),
        session_id,
    )
    response = StreamingResponse(
        stream_chat_response(request.messages, session_id),
        media_type="text/event-stream",
    )
    # ponytail: secure mirrors the scheme uvicorn itself sees — if this ever
    # sits behind a TLS-terminating proxy (e.g. Caddy) run uvicorn with
    # --proxy-headers, or the cookie's Secure flag silently stays off even
    # though users are on https.
    response.set_cookie(
        "session_id",
        session_id,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=http_request.url.scheme == "https",
    )
    return response

@app.post("/api/session/user-info")
async def store_user_info(request: UserInfoRequest) -> dict:
    """Store captured user contact information in their Redis session."""
    if not request.session_id:
        return {"status": "error", "message": "No session ID provided"}
        
    logger.info("POST /api/session/user-info — session=%s", request.session_id)
    await save_user_info(
        request.session_id, 
        request.user_info.name, 
        request.user_info.phone, 
        request.user_info.email
    )
    return {"status": "ok"}
