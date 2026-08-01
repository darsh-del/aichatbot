"""Per-IP sliding-window rate limiter as a Starlette middleware.

ponytail: in-memory single-process — timestamps live in a dict, so limits reset
on restart and don't sync across workers. Fine for a single uvicorn worker on a
demo/free-tier deploy. Upgrade to a Redis-backed limiter (e.g. slowapi) if you
run multiple workers or need limits to survive restarts.
"""
import logging
from collections import defaultdict, deque
from time import monotonic

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

CHAT_LIMIT_PER_MINUTE = 20
CHAT_PATH = "/api/chat"

_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path != CHAT_PATH:
            return await call_next(request)

        now = monotonic()
        ip = _client_ip(request)
        hits = _hits[ip]

        cutoff = now - 60.0
        while hits and hits[0] < cutoff:
            hits.popleft()

        if len(hits) >= CHAT_LIMIT_PER_MINUTE:
            logger.warning("Rate limit hit: IP=%s (%d requests in last 60s)", ip, len(hits))
            return JSONResponse(
                {"detail": "Too many requests. Please slow down."},
                status_code=429,
            )

        hits.append(now)
        return await call_next(request)
