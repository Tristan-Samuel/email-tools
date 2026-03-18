from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for

from .services.email_parser import parse_email_upload
from .services.groq_client import GroqClient
from .services.summary import build_digest, build_email_record


bp = Blueprint("main", __name__)


def get_store():
    return current_app.extensions["email_store"]


def get_groq_client() -> GroqClient:
    return GroqClient(
        api_key=current_app.config.get("GROQ_API_KEY", ""),
        default_model=current_app.config.get("GROQ_DEFAULT_MODEL", "llama-3.3-70b-versatile"),
    )


def require_login():
    if not getattr(g, "current_user_email", ""):
        flash("Log in with your email to access your inbox tools.", "error")
        return redirect(url_for("main.login"))
    return None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user_email = (request.form.get("email") or "").strip().lower()
        if "@" not in user_email or "." not in user_email.split("@")[-1]:
            flash("Enter a valid email address.", "error")
            return render_template("login.html")

        session["user_email"] = user_email
        flash("Logged in successfully.", "success")
        return redirect(url_for("main.dashboard"))

    if getattr(g, "current_user_email", ""):
        return redirect(url_for("main.dashboard"))

    return render_template("login.html")


@bp.post("/logout")
def logout():
    session.pop("user_email", None)
    flash("You have been logged out.", "success")
    return redirect(url_for("main.login"))


@bp.get("/")
def dashboard():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    category = request.args.get("category") or None
    query = request.args.get("query", "").strip()
    user_email = g.current_user_email

    if query:
        emails = store.search(query, user_email=user_email)
    else:
        emails = store.list_emails(category=category, user_email=user_email)

    stats = store.get_stats(user_email=user_email)
    categories = store.get_categories(user_email=user_email)
    digest = build_digest(store.list_emails(limit=50, user_email=user_email))

    return render_template(
        "dashboard.html",
        emails=emails,
        stats=stats,
        categories=categories,
        digest=digest,
        selected_category=category,
        query=query,
    )


@bp.post("/upload")
def upload():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    files = [file for file in request.files.getlist("email_files") if file and file.filename]
    if not files:
        flash("Select one or more .eml or .mbox files to analyze.", "error")
        return redirect(url_for("main.dashboard"))

    store = get_store()
    groq_client = get_groq_client()
    user_email = g.current_user_email
    imported_count = 0

    for file in files:
        upload_path = Path(current_app.config["UPLOAD_FOLDER"]) / file.filename
        file.save(upload_path)
        try:
            parsed_messages = parse_email_upload(upload_path)
        except ValueError as exc:
            flash(str(exc), "error")
            continue

        records = [
            build_email_record(
                message,
                file.filename,
                user_email=user_email,
                groq_client=groq_client,
            )
            for message in parsed_messages
        ]
        imported_count += store.bulk_upsert(records)

    if groq_client.enabled:
        flash(f"Analyzed {imported_count} emails with Groq-powered summaries.", "success")
    else:
        flash(f"Analyzed {imported_count} emails and refreshed the cached summaries.", "success")
    return redirect(url_for("main.dashboard"))


@bp.get("/email/<email_id>")
def email_detail(email_id: str):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    email = get_store().get_email(email_id, user_email=g.current_user_email)
    if email is None:
        flash("That email could not be found.", "error")
        return redirect(url_for("main.dashboard"))

    return render_template("email_detail.html", email=email)


def register_routes(app):
    app.register_blueprint(bp)