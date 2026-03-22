from __future__ import annotations

import html as _html
import os
from pathlib import Path

from flask import Flask, g, request, session
from markupsafe import Markup

from .routes import register_routes
from .services.store import EmailStore


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", "dev"),
        DATABASE=Path(app.instance_path) / "email_tools.db",
        UPLOAD_FOLDER=Path(app.instance_path) / "uploads",
        MAX_CONTENT_LENGTH=50 * 1024 * 1024,
        GROQ_API_KEY=os.environ.get("GROQ_API_KEY", ""),
        GROQ_DEFAULT_MODEL=os.environ.get("GROQ_DEFAULT_MODEL", "llama-3.3-70b-versatile"),
        STATIC_VERSION="14",
    )

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config["UPLOAD_FOLDER"].mkdir(parents=True, exist_ok=True)

    store = EmailStore(app.config["DATABASE"])
    store.initialize()
    app.extensions["email_store"] = store

    @app.before_request
    def load_current_user() -> None:
        g.current_user_email = (session.get("user_email") or "").strip().lower()

    @app.context_processor
    def inject_current_user() -> dict:
        user_email = getattr(g, "current_user_email", "")
        active_accounts: list = []
        if user_email:
            try:
                active_accounts = store.list_imap_accounts(user_email)
            except Exception:
                pass
        source_account = request.args.get("source_account") if request else None
        query = request.args.get("query", "") if request else ""
        return {
            "current_user_email": user_email,
            "active_accounts": active_accounts,
            "source_account": source_account,
            "query": query,
            "static_version": app.config.get("STATIC_VERSION", "1"),
        }

    @app.template_filter("datetimeformat")
    def datetimeformat(value: str | None) -> str:
        if not value:
            return "Unknown time"
        return value.replace("T", " ").replace("+00:00", " UTC")

    @app.template_filter("format_email_body")
    def format_email_body(body: str | None) -> Markup:
        """Render plain-text email body as safe HTML paragraphs with blockquote support."""
        if not body or not body.strip():
            return Markup("<p><em>No body content.</em></p>")
        result: list[str] = []
        for para in body.split("\n\n"):
            if not para.strip():
                continue
            lines = para.split("\n")
            non_empty = [l for l in lines if l.strip()]
            if non_empty and all(l.lstrip().startswith(">") for l in non_empty):
                inner = _html.escape("\n".join(l.lstrip("> ") for l in lines))
                result.append(f'<blockquote class="email-quote">{inner}</blockquote>')
            else:
                content = _html.escape(para).replace("\n", "<br>")
                result.append(f"<p>{content}</p>")
        return Markup("\n".join(result) or "<p><em>No body content.</em></p>")

    register_routes(app)
    return app