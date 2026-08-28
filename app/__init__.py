from __future__ import annotations

import datetime as _dt
import html as _html
import os
import re
import secrets
from pathlib import Path

from flask import Flask, g, request, session
from flask_wtf.csrf import CSRFProtect
from markupsafe import Markup

from .routes import register_routes
from .services.gemini_client import DEFAULT_GEMINI_MODEL, resolve_gemini_model
from .services.groq_client import DEFAULT_CHAT_MODEL, resolve_chat_model
from .services.store import EmailStore

csrf = CSRFProtect()


def _load_secret_key(instance_path: Path) -> str:
    env_key = os.environ.get("FLASK_SECRET_KEY", "").strip()
    if env_key:
        return env_key

    is_production = os.environ.get("FLASK_ENV") == "production" or os.environ.get("ENV") == "production"
    if is_production:
        raise RuntimeError(
            "FLASK_SECRET_KEY must be set in production. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    key_file = instance_path / "secret_key"
    if key_file.is_file():
        return key_file.read_text(encoding="utf-8").strip()

    generated = secrets.token_hex(32)
    key_file.write_text(generated, encoding="utf-8")
    return generated


def _credential_encryption_key(secret_key: str) -> str:
    dedicated = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "").strip()
    return dedicated or secret_key


def _load_env_file(path: Path) -> None:
    """Fill os.environ from `.env` without overriding vars already set."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = value.strip().strip("'").strip('"')


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    if "PYTEST_CURRENT_TEST" not in os.environ:
        _load_env_file(Path(__file__).resolve().parent.parent / ".env")

    secret_key = _load_secret_key(Path(app.instance_path))
    groq_model = resolve_chat_model(os.environ.get("GROQ_DEFAULT_MODEL", DEFAULT_CHAT_MODEL))
    gemini_model = resolve_gemini_model(os.environ.get("GEMINI_DEFAULT_MODEL", DEFAULT_GEMINI_MODEL))
    app.config.from_mapping(
        SECRET_KEY=secret_key,
        CREDENTIAL_ENCRYPTION_KEY=_credential_encryption_key(secret_key),
        DATABASE=Path(app.instance_path) / "email_tools.db",
        UPLOAD_FOLDER=Path(app.instance_path) / "uploads",
        MAX_CONTENT_LENGTH=50 * 1024 * 1024,
        GROQ_API_KEY=os.environ.get("GROQ_API_KEY", ""),
        GROQ_DEFAULT_MODEL=groq_model,
        GEMINI_API_KEY=os.environ.get("GEMINI_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", ""),
        GEMINI_DEFAULT_MODEL=gemini_model,
        SMTP_HOST=os.environ.get("SMTP_HOST", "").strip(),
        SMTP_PORT=int(os.environ.get("SMTP_PORT", "587")),
        SMTP_USERNAME=os.environ.get("SMTP_USERNAME", "").strip(),
        SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD", ""),
        SMTP_FROM=os.environ.get("SMTP_FROM", "").strip(),
        SMTP_USE_TLS=os.environ.get("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes"),
        STATIC_VERSION="29",
    )

    app.config["UPLOAD_FOLDER"].mkdir(parents=True, exist_ok=True)

    csrf.init_app(app)

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
        activity_job = None
        ai_pending = 0
        ai_analyzed = 0
        groq_available = False
        if user_email:
            try:
                activity_job = store.get_latest_job(user_email)
                ai_analyzed, ai_pending = store.count_ai_stats(user_email)
            except Exception:
                pass
            try:
                from .routes import get_ai_client

                groq_available = get_ai_client(user_email).enabled
            except Exception:
                groq_available = bool(
                    app.config.get("GEMINI_API_KEY") or app.config.get("GROQ_API_KEY")
                )
        return {
            "current_user_email": user_email,
            "active_accounts": active_accounts,
            "source_account": source_account,
            "query": query,
            "static_version": app.config.get("STATIC_VERSION", "1"),
            "activity_job": activity_job,
            "ai_pending": ai_pending,
            "ai_analyzed": ai_analyzed,
            "groq_available": groq_available,
        }

    @app.template_filter("datetimeformat")
    def datetimeformat(value: str | None) -> str:
        if not value:
            return "Unknown time"
        try:
            dt = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_dt.timezone.utc)
            now = _dt.datetime.now(_dt.timezone.utc)
            diff = now - dt
            if diff.days == 0 and diff.total_seconds() < 86400:
                hours = int(diff.total_seconds() // 3600)
                if hours < 1:
                    mins = max(1, int(diff.total_seconds() // 60))
                    return f"{mins}m ago"
                return f"{hours}h ago"
            if diff.days < 7:
                return f"{diff.days}d ago"
            local = dt.astimezone()
            hour = local.strftime("%I").lstrip("0") or "12"
            return f"{local.strftime('%b')} {local.day}, {hour}:{local.strftime('%M %p')}"
        except ValueError:
            return value.replace("T", " ").replace("+00:00", " UTC")

    @app.template_filter("sanitize_bullet")
    def sanitize_bullet_filter(value: str | None) -> Markup:
        from .services.summary import sanitize_bullet_text

        return Markup(sanitize_bullet_text(value or ""))

    @app.template_filter("row_line")
    def row_line_filter(email: dict | None) -> str:
        from .services.summary import email_row_summaries

        if not email:
            return ""
        return email_row_summaries(email)[0]

    @app.template_filter("row_compact")
    def row_compact_filter(email: dict | None) -> str:
        from .services.summary import email_row_summaries

        if not email:
            return ""
        return email_row_summaries(email)[1]

    @app.template_filter("sender_name")
    def sender_name_filter(value: str | None) -> str:
        raw = (value or "Unknown sender").strip()
        if "<" in raw:
            name = raw.split("<")[0].strip()
            return name or raw
        return raw

    def _format_image_chips(text: str) -> str:
        image_re = re.compile(r"\[image:\s*([^\]]*)\]", re.I)

        def _chip(match: re.Match[str]) -> str:
            label = (match.group(1) or "image").strip() or "image"
            return f'<span class="email-img-placeholder">[{_html.escape(label)}]</span>'

        return image_re.sub(_chip, text)

    def _linkify_body_paragraph(para: str) -> str:
        """Escape paragraph text; linkify short labels and bare URLs."""
        label_url = re.compile(
            r"(?:^|[\s(])((?:[^\s<\n]{1,60}))\s*<(https?://[^>\s]+)>",
            re.I,
        )
        raw_url = re.compile(r'(?<![\w/@])(https?://[^\s<>"\']+)', re.I)
        text = _format_image_chips(_html.escape(para))
        parts: list[str] = []
        last = 0
        for match in label_url.finditer(text):
            if match.start() > last:
                parts.append(text[last:match.start()])
            prefix = match.group(0)[: match.start(1) - match.start()]
            label = match.group(1).strip()
            url = match.group(2).strip()
            safe_url = _html.escape(url, quote=True)
            safe_label = _html.escape(label or url[:48])
            parts.append(
                f'{prefix}<a href="{safe_url}" target="_blank" rel="noopener noreferrer">{safe_label}</a>'
            )
            last = match.end()
        if last < len(text):
            parts.append(text[last:])
        linked = "".join(parts)
        linked = raw_url.sub(
            lambda m: (
                f'<a href="{_html.escape(m.group(1), quote=True)}" target="_blank" '
                f'rel="noopener noreferrer">{_html.escape(m.group(1)[:72])}</a>'
            ),
            linked,
        )
        return linked.replace("\n", "<br>")

    def _is_forward_block(para: str) -> bool:
        lower = para.lower()
        if "begin forwarded message" in lower or "sent from my iphone" in lower:
            return True
        lines = [line.strip() for line in para.split("\n") if line.strip()]
        header_hits = sum(
            1
            for line in lines
            if re.match(r"^(From|Date|To|Cc|Subject|Sent):\s", line, re.I)
        )
        return header_hits >= 2

    @app.template_filter("format_email_body")
    def format_email_body(body: str | None) -> Markup:
        """Render plain-text email body as safe HTML paragraphs with blockquote support."""
        from .services.email_parser import expand_inline_breaks

        if not body or not body.strip():
            return Markup("<p><em>No body content.</em></p>")
        body = expand_inline_breaks(body)
        result: list[str] = []
        for para in body.split("\n\n"):
            if not para.strip():
                continue
            lines = para.split("\n")
            non_empty = [line for line in lines if line.strip()]
            if non_empty and all(line.lstrip().startswith(">") for line in non_empty):
                inner = _html.escape("\n".join(line.lstrip("> ") for line in non_empty))
                result.append(f'<blockquote class="email-quote">{inner}</blockquote>')
            elif _is_forward_block(para):
                inner = _linkify_body_paragraph(para)
                result.append(f'<blockquote class="email-quote email-forward">{inner}</blockquote>')
            else:
                content = _linkify_body_paragraph(para)
                result.append(f"<p>{content}</p>")
        return Markup("\n".join(result) or "<p><em>No body content.</em></p>")

    register_routes(app)
    return app
