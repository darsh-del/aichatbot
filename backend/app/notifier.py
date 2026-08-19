import asyncio
import logging
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app.config import settings

logger = logging.getLogger(__name__)

# Cache to store the last time an alert was sent (to debounce rapid-fire errors)
_last_alert_time: float = 0.0
# Only allow one out-of-credits email per hour (3600 seconds)
ALERT_DEBOUNCE_SECONDS = 3600


def _send_email_sync(subject: str, body: str) -> None:
    """Synchronous core for sending an email via SMTP."""
    if not all([settings.smtp_server, settings.smtp_user, settings.smtp_pass, settings.smtp_to]):
        logger.warning("SMTP configuration is incomplete. Skipping email alert.")
        return

    msg = MIMEMultipart()
    msg["From"] = settings.smtp_user
    msg["To"] = settings.smtp_to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        # Connect to SMTP server
        server = smtplib.SMTP(settings.smtp_server, settings.smtp_port)
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_pass)
        server.send_message(msg)
        server.quit()
        logger.info(f"Successfully sent alert email to {settings.smtp_to}")
    except Exception as e:
        logger.error(f"Failed to send alert email: {e}")


async def notify_credit_exhausted(error_message: str) -> None:
    """
    Background task to email admins when the LLM runs out of credits (404/402 etc).
    Includes a 1-hour debounce so it doesn't spam the inbox if multiple users hit it.
    """
    global _last_alert_time
    now = time.time()

    if now - _last_alert_time < ALERT_DEBOUNCE_SECONDS:
        logger.info("Credit exhaustion alert throttled (already sent recently).")
        return

    _last_alert_time = now

    subject = "URGENT: AI Chatbot Out of Credits / API Error!"
    body = (
        "Hello,\n\n"
        "Your AI Chatbot just encountered a critical API error. This is likely because "
        "your API provider (OpenAI, Anthropic, etc.) has run out of credits or blocked the request.\n\n"
        f"Raw Error Message:\n{error_message}\n\n"
        "Please check your billing dashboard immediately to restore service.\n"
    )

    # Run the synchronous email sending in a background thread so we don't block FastAPI
    await asyncio.to_thread(_send_email_sync, subject, body)
