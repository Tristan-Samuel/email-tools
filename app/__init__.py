import os
from pathlib import Path

from flask import Flask, g, session

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
        return {"current_user_email": getattr(g, "current_user_email", "")}

    @app.template_filter("datetimeformat")
    def datetimeformat(value: str | None) -> str:
        if not value:
            return "Unknown time"

        return value.replace("T", " ").replace("+00:00", " UTC")

    register_routes(app)
    return app