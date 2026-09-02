from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_email_tools_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep pytest off the live instance/email_tools.db and skip loading .env secrets."""
    db_path = tmp_path / "email_tools.db"
    monkeypatch.setenv("FLASK_SECRET_KEY", "pytest-flask-secret-not-for-production")
    monkeypatch.setenv("EMAIL_TOOLS_DATABASE", str(db_path))
    monkeypatch.delenv("SIGNUP_ALLOWED_EMAIL", raising=False)
    monkeypatch.delenv("SIGNUP_INVITE_TOKEN", raising=False)
    monkeypatch.delenv("SIGNUP_OPEN", raising=False)
    monkeypatch.delenv("FLASK_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    return db_path
