import asyncio
import logging
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict

from app.config import settings

logger = logging.getLogger(__name__)

# Dictionary to store the last time an alert was sent for each specific category
_last_alert_times: Dict[str, float] = {}

# Default debounce times for different alert categories (in seconds)
ALERT_DEBOUNCE_CONFIG = {
    "llm_credits": 3600,      # 1 hour
    "llm_rate_limit": 1800,   # 30 minutes
    "llm_outage": 1800,       # 30 minutes
    "redis_down": 900,        # 15 minutes
    "weaviate_down": 900,     # 15 minutes
    "mcp_tool_error": 1800,   # 30 minutes
    "default": 3600           # 1 hour fallback
}


def _send_email_sync(subject: str, body: str) -> None:
    """Synchronous core for sending an email via SMTP."""
    if not all([settings.smtp_server, settings.smtp_user, settings.smtp_pass, settings.smtp_to]):
        logger.warning("SMTP configuration is incomplete. Skipping email alert for: %s", subject)
        return

    msg = MIMEMultipart()
    msg["From"] = settings.smtp_user
    msg["To"] = settings.smtp_to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP(settings.smtp_server, settings.smtp_port, timeout=10)
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_pass)
        server.send_message(msg)
        server.quit()
        logger.info(f"Successfully sent alert email to {settings.smtp_to}")
    except Exception as e:
        logger.error(f"Failed to send alert email: {e}")


async def send_critical_alert(alert_type: str, error_message: str, context: str = "") -> None:
    """
    Background task to email admins when a critical infrastructure piece fails.
    Uses category-specific debounce timers to prevent inbox spam.
    """
    global _last_alert_times
    now = time.time()
    
    debounce_seconds = ALERT_DEBOUNCE_CONFIG.get(alert_type, ALERT_DEBOUNCE_CONFIG["default"])
    last_sent = _last_alert_times.get(alert_type, 0.0)

    if now - last_sent < debounce_seconds:
        logger.info("Alert '%s' throttled (already sent recently).", alert_type)
        return

    _last_alert_times[alert_type] = now

    subject_map = {
        "llm_credits": "URGENT: AI Chatbot Out of Credits (402/404)!",
        "llm_rate_limit": "WARNING: AI Chatbot Hitting API Rate Limits (429)",
        "llm_outage": "CRITICAL: Upstream LLM Provider Outage (500+)",
        "redis_down": "CRITICAL: Redis Database Unreachable!",
        "weaviate_down": "CRITICAL: Weaviate Vector Database Unreachable!",
        "mcp_tool_error": "WARNING: External MCP Tool API Failing!"
    }
    
    subject = subject_map.get(alert_type, f"ALERT: Chatbot Error - {alert_type}")
    
    body = (
        f"Hello,\n\n"
        f"Your AI Chatbot just encountered a critical infrastructure error.\n\n"
        f"Alert Type: {alert_type}\n"
        f"Context: {context}\n\n"
        f"Raw Error Message:\n{error_message}\n\n"
        f"Please check your server logs and provider dashboards immediately.\n"
    )

    await asyncio.to_thread(_send_email_sync, subject, body)
