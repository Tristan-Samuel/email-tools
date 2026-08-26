"""Outbound email for signup verification codes (stdlib SMTP only)."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from flask import current_app

logger = logging.getLogger(__name__)


def smtp_configured() -> bool:
    """Return True when SMTP_HOST is set."""
    return bool((current_app.config.get("SMTP_HOST") or "").strip())


def send_email(to: str, subject: str, body: str) -> tuple[bool, str]:
    """Return (ok, error_message)."""
    host = (current_app.config.get("SMTP_HOST") or "").strip()
    if not host:
        return False, "SMTP is not configured."

    port = int(current_app.config.get("SMTP_PORT", 587))
    username = (current_app.config.get("SMTP_USERNAME") or "").strip()
    password = current_app.config.get("SMTP_PASSWORD") or ""
    from_addr = (current_app.config.get("SMTP_FROM") or username or "").strip()
    use_tls = current_app.config.get("SMTP_USE_TLS", True)

    if not from_addr:
        return False, "SMTP_FROM or SMTP_USERNAME must be set."

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_addr
    message["To"] = to
    message.set_content(body)

    try:
        if use_tls:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                if username:
                    smtp.login(username, password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                if username:
                    smtp.login(username, password)
                smtp.send_message(message)
        return True, ""
    except Exception as exc:
        logger.exception("SMTP send failed to %s", to)
        return False, str(exc)
