from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for

from .services import crypto, imap_service
from .services.email_parser import parse_email_upload
from .services.groq_client import GroqClient
from .services.summary import build_digest, build_email_record


bp = Blueprint("main", __name__)


def get_store():
    return current_app.extensions["email_store"]


def get_groq_client() -> GroqClient:
    # Allow a per-user Groq key stored in DB to override the env/config key.
    user_api_key = ""
    if getattr(g, "current_user_email", ""):
        try:
            user_api_key = get_store().get_setting(g.current_user_email, "groq_api_key")
        except Exception:
            pass
    api_key = user_api_key or current_app.config.get("GROQ_API_KEY", "")
    return GroqClient(
        api_key=api_key,
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
    source_account = request.args.get("source_account") or None
    user_email = g.current_user_email

    if query:
        emails = store.search(query, user_email=user_email, source_account=source_account)
    else:
        emails = store.list_emails(category=category, user_email=user_email, source_account=source_account)

    stats = store.get_stats(user_email=user_email, source_account=source_account)
    categories = store.get_categories(user_email=user_email, source_account=source_account)
    digest = build_digest(store.list_emails(limit=50, user_email=user_email, source_account=source_account))
    imap_accounts = store.list_imap_accounts(user_email)

    return render_template(
        "dashboard.html",
        emails=emails,
        stats=stats,
        categories=categories,
        digest=digest,
        selected_category=category,
        query=query,
        imap_accounts=imap_accounts,
        source_account=source_account,
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


# ---------------------------------------------------------------------------
# Account management
# ---------------------------------------------------------------------------

@bp.route("/accounts", methods=["GET"])
def accounts():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    imap_accounts = get_store().list_imap_accounts(g.current_user_email)
    return render_template("accounts.html", imap_accounts=imap_accounts)


@bp.route("/accounts/add", methods=["GET", "POST"])
def accounts_add():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    if request.method == "POST":
        account_email = (request.form.get("account_email") or "").strip().lower()
        password = request.form.get("password") or ""
        imap_host = (request.form.get("imap_host") or "imap.gmail.com").strip()
        imap_port = int(request.form.get("imap_port") or 993)

        if "@" not in account_email or not password:
            flash("Email address and password are required.", "error")
            return render_template("accounts.html", imap_accounts=get_store().list_imap_accounts(g.current_user_email), show_add_form=True)

        # Test credentials before saving
        ok, err = imap_service.test_connection(imap_host, imap_port, account_email, password)
        if not ok:
            flash(f"Could not connect to {imap_host}: {err}", "error")
            return render_template("accounts.html", imap_accounts=get_store().list_imap_accounts(g.current_user_email), show_add_form=True)

        encrypted = crypto.encrypt(password, current_app.config["SECRET_KEY"])
        get_store().save_imap_account(
            user_email=g.current_user_email,
            account_email=account_email,
            imap_host=imap_host,
            imap_port=imap_port,
            encrypted_password=encrypted,
        )
        flash(f"Account {account_email} connected successfully.", "success")
        return redirect(url_for("main.accounts"))

    return render_template("accounts.html", imap_accounts=get_store().list_imap_accounts(g.current_user_email), show_add_form=True)


@bp.post("/accounts/delete/<int:account_id>")
def accounts_delete(account_id: int):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    get_store().delete_imap_account(account_id, g.current_user_email)
    flash("Account removed.", "success")
    return redirect(url_for("main.accounts"))


@bp.post("/accounts/sync/<int:account_id>")
def accounts_sync(account_id: int):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    account = store.get_imap_account(account_id, g.current_user_email)
    if account is None:
        flash("Account not found.", "error")
        return redirect(url_for("main.accounts"))

    password = crypto.decrypt(account["encrypted_password"], current_app.config["SECRET_KEY"])
    if not password:
        flash("Could not decrypt stored credentials. Please re-add this account.", "error")
        return redirect(url_for("main.accounts"))

    try:
        emails_raw, max_uid = imap_service.fetch_emails(
            host=account["imap_host"],
            port=account["imap_port"],
            username=account["account_email"],
            password=password,
            since_uid=account["last_uid"] or 0,
        )
    except Exception as exc:
        flash(f"IMAP sync failed: {exc}", "error")
        return redirect(url_for("main.accounts"))

    groq_client = get_groq_client()
    records = [
        build_email_record(
            msg,
            source_name=account["account_email"],
            user_email=g.current_user_email,
            source_account=account["account_email"],
            groq_client=groq_client,
        )
        for msg in emails_raw
    ]
    imported = store.bulk_upsert(records)
    store.update_imap_last_sync(account_id, max_uid)

    flash(f"Synced {imported} new email(s) from {account['account_email']}.", "success")
    return redirect(url_for("main.accounts"))


# ---------------------------------------------------------------------------
# Settings (Groq API key)
# ---------------------------------------------------------------------------

@bp.route("/settings", methods=["GET", "POST"])
def settings():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    if request.method == "POST":
        groq_key = (request.form.get("groq_api_key") or "").strip()
        store.save_setting(g.current_user_email, "groq_api_key", groq_key)
        flash("Settings saved.", "success")
        return redirect(url_for("main.settings"))

    saved_key = store.get_setting(g.current_user_email, "groq_api_key")
    active_model = current_app.config.get("GROQ_DEFAULT_MODEL", "llama-3.3-70b-versatile")
    return render_template("settings.html", saved_key=saved_key, active_model=active_model)


def register_routes(app):
    app.register_blueprint(bp)