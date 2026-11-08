"""Localhost calls to the tssamuel login platform. The key and mailbox stay there."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from flask import current_app


class PlatformError(Exception):
    def __init__(self, message: str, code: str = "error"):
        super().__init__(message)
        self.message = message
        self.code = code


_MESSAGES = {
    "not_enabled": "This app is not allowed to use the shared service.",
    "not_configured": "The shared service is not configured.",
    "cap": "The daily limit for this app is used up.",
    "rate_limited": "Too many requests. Try again in a minute.",
    "gemini_unavailable": "Gemini did not answer.",
    "mail_failed": "Could not send email.",
    "bad_request": "The request was rejected.",
    "invalid_client": "This app could not sign in to the shared service.",
}


def platform_configured() -> bool:
    cfg = current_app.config
    return bool(
        (cfg.get("LOGIN_TOKEN_URL") or "").strip()
        and (cfg.get("LOGIN_CLIENT_ID") or "").strip()
        and (cfg.get("LOGIN_CLIENT_SECRET") or "").strip()
    )


def _post(path: str, payload: dict, timeout: float) -> dict:
    base = (current_app.config.get("LOGIN_TOKEN_URL") or "").rstrip("/")
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base}{path}",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            data = {}
        code = str(data.get("error") or "error")
        raise PlatformError(_MESSAGES.get(code, "The shared service refused the request."), code) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PlatformError("Could not reach the login service.", "unreachable") from exc
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError) as exc:
        raise PlatformError("The login service returned an unreadable response.", "bad_response") from exc
    if not isinstance(data, dict):
        raise PlatformError("The login service returned an unreadable response.", "bad_response")
    return data


def _auth() -> dict:
    return {
        "client_id": current_app.config.get("LOGIN_CLIENT_ID") or "",
        "client_secret": current_app.config.get("LOGIN_CLIENT_SECRET") or "",
    }


def call_gemini(
    *,
    model: str,
    system: str,
    contents: object,
    generation_config: dict | None = None,
    user_email: str = "",
    timeout: float = 120,
) -> dict:
    payload = _auth()
    payload.update(
        {
            "model": model,
            "system": system,
            "contents": contents,
            "generation_config": generation_config or {},
            "user_email": user_email,
        }
    )
    return _post("/platform/gemini", payload, timeout)


def send_platform_mail(to_addr: str, subject: str, text: str, *, timeout: float = 20) -> None:
    payload = _auth()
    payload.update({"to": to_addr, "subject": subject, "text": text})
    _post("/platform/mail", payload, timeout)
