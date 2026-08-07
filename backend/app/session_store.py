import json
import logging
from typing import Any

from redis.asyncio import Redis, from_url

from app.config import settings

logger = logging.getLogger(__name__)

# Global redis connection pool
redis_client: Redis | None = None

async def init_redis():
    """Initialize the Redis connection pool."""
    global redis_client
    if settings.redis_url:
        try:
            redis_client = from_url(settings.redis_url, decode_responses=True)
            await redis_client.ping()
            logger.info(f"Connected to Redis at {settings.redis_url}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            redis_client = None

async def close_redis():
    """Close the Redis connection pool."""
    global redis_client
    if redis_client:
        await redis_client.aclose()
        redis_client = None

async def save_turn(session_id: str, user_msg: str, assistant_msg: str) -> None:
    """Persist a conversation turn to Redis and increment the message count.
    Refreshes the TTL on the session.
    """
    if not redis_client or not session_id:
        return

    key = f"session:{session_id}"
    try:
        # Load existing session or create new
        session_data = await redis_client.hgetall(key)
        
        # Parse existing messages or start empty list
        messages = []
        if session_data and "messages" in session_data:
            try:
                messages = json.loads(session_data["messages"])
            except json.JSONDecodeError:
                pass
                
        # Append the new turn
        messages.append({"role": "user", "content": user_msg})
        messages.append({"role": "assistant", "content": assistant_msg})
        
        # Calculate new message count
        count = int(session_data.get("message_count", 0)) + 1 if session_data else 1
        
        # Build update dictionary
        update = {
            "messages": json.dumps(messages),
            "message_count": str(count)
        }
        
        # Write to redis and set TTL
        await redis_client.hset(key, mapping=update)
        await redis_client.expire(key, settings.session_ttl_seconds)
    except Exception as e:
        logger.error(f"Failed to save turn to Redis for session {session_id}: {e}")

async def get_message_count(session_id: str) -> int:
    """Get the number of user messages in this session."""
    if not redis_client or not session_id:
        return 0
        
    try:
        count = await redis_client.hget(f"session:{session_id}", "message_count")
        return int(count) if count else 0
    except Exception:
        return 0

async def should_prompt_login(session_id: str) -> bool:
    """Check if we should prompt the user for login/details.
    True if message count >= configured threshold AND not yet prompted AND no user info.
    """
    if not redis_client or not session_id:
        return False
        
    try:
        key = f"session:{session_id}"
        session_data = await redis_client.hgetall(key)
        
        if not session_data:
            return False
            
        count = int(session_data.get("message_count", 0))
        prompted = session_data.get("login_prompted", "false") == "true"
        has_info = "user_info" in session_data
        
        return (count >= settings.login_prompt_after) and not prompted and not has_info
    except Exception as e:
        logger.error(f"Failed to check login prompt status: {e}")
        return False

async def mark_login_prompted(session_id: str) -> None:
    """Mark that the login prompt has been shown so it doesn't re-trigger."""
    if not redis_client or not session_id:
        return
        
    try:
        key = f"session:{session_id}"
        await redis_client.hset(key, "login_prompted", "true")
        await redis_client.expire(key, settings.session_ttl_seconds)
    except Exception as e:
        logger.error(f"Failed to mark login prompted: {e}")

async def save_user_info(session_id: str, name: str, phone: str, email: str) -> None:
    """Store the captured user info in the session."""
    if not redis_client or not session_id:
        return
        
    try:
        key = f"session:{session_id}"
        user_info = json.dumps({"name": name, "phone": phone, "email": email})
        await redis_client.hset(key, "user_info", user_info)
        await redis_client.expire(key, settings.session_ttl_seconds)
    except Exception as e:
        logger.error(f"Failed to save user info: {e}")
