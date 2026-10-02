from __future__ import annotations

import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import requests
from flask import current_app, redirect, request, session


class SSOError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class SSOIdentity:
    sub: str
    email: str
    email_verified: bool
    name: str
    google_linked: bool


def sso_enabled() -> bool:
    cfg = current_app.config
    return bool(
        (cfg.get("LOGIN_URL") or "").strip()
        and (cfg.get("LOGIN_CLIENT_ID") or "").strip()
        and (cfg.get("LOGIN_CLIENT_SECRET") or "").strip()
        and (cfg.get("LOGIN_REDIRECT_URI") or "").strip()
    )


def start_authorize(*, next_url: str = "/"):
    state = secrets.token_urlsafe(24)
    session["sso_state"] = state
    session["sso_next"] = next_url
    params = urlencode(
        {
            "client_id": current_app.config["LOGIN_CLIENT_ID"],
            "redirect_uri": current_app.config["LOGIN_REDIRECT_URI"],
            "state": state,
        }
    )
    return redirect(f"{current_app.config['LOGIN_URL'].rstrip('/')}/authorize?{params}")


def identity_from_callback() -> SSOIdentity:
    state = (request.args.get("state") or "").strip()
    code = (request.args.get("code") or "").strip()
    expected = session.pop("sso_state", None)
    if not state or not expected or not secrets.compare_digest(state, expected):
        raise SSOError("Sign-in could not be verified. Try again.")
    if not code:
        raise SSOError("Sign-in was cancelled.")
    token_base = (current_app.config.get("LOGIN_TOKEN_URL") or "").strip() or "http://127.0.0.1:5111"
    try:
        response = requests.post(
            f"{token_base.rstrip('/')}/token",
            json={
                "client_id": current_app.config["LOGIN_CLIENT_ID"],
                "client_secret": current_app.config["LOGIN_CLIENT_SECRET"],
                "code": code,
            },
            timeout=8,
        )
    except requests.RequestException as exc:
        raise SSOError("Could not reach the login service.") from exc
    if response.status_code != 200:
        raise SSOError("Sign-in expired. Try again.")
    data = response.json()
    sub = str(data.get("sub") or "").strip()
    email = str(data.get("email") or "").strip().lower()
    if not sub or "@" not in email:
        raise SSOError("The login service did not return an account.")
    return SSOIdentity(
        sub=sub,
        email=email,
        email_verified=bool(data.get("email_verified")),
        name=str(data.get("name") or "").strip(),
        google_linked=bool(data.get("google_linked")),
    )
