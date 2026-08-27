from __future__ import annotations

import datetime
import hashlib
import json
import logging
import os
import secrets
import uuid
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

from flask import Blueprint, current_app, flash, g, has_request_context, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from .services import crypto, imap_service, mail
from .services.email_parser import parse_email_upload
from .services.groq_client import (
    DEFAULT_CHAT_MODEL,
    GroqClient,
    is_fatal_groq_auth_error,
    is_rate_limit_error,
)
from .services.summary import build_digest, build_email_record, build_important_items
from .services import sync_worker
from .services.sync_worker import JobCancelled, check_cancelled, current_job_is_cancelled

logger = logging.getLogger(__name__)

_VERIFICATION_TTL = datetime.timedelta(minutes=10)
_RESEND_COOLDOWN = datetime.timedelta(seconds=60)
_MAX_VERIFICATION_ATTEMPTS = 5


bp = Blueprint("main", __name__)

def _guess_imap_host(email: str) -> str:
    return imap_service.guess_imap_host(email)


def _guess_imap_port(email: str, host: str) -> int:
    return imap_service.guess_imap_port(email, host)


def _parse_imap_form() -> tuple[dict | None, str]:
    """Validate add-account form fields. Return (payload, error_message)."""
    account_email = (request.form.get("account_email") or "").strip().lower()
    password = request.form.get("password") or ""
    provided_host = (request.form.get("imap_host") or "").strip()
    imap_host = imap_service.resolve_imap_host(account_email, provided_host)
    try:
        imap_port = int(request.form.get("imap_port") or _guess_imap_port(account_email, imap_host))
    except ValueError:
        imap_port = _guess_imap_port(account_email, imap_host)
    if imap_port < 1 or imap_port > 65535:
        imap_port = _guess_imap_port(account_email, imap_host)
    if "@" not in account_email or not password:
        return None, "Email address and App Password are required."
    if not imap_host:
        return None, "IMAP host is required."
    return {
        "account_email": account_email,
        "password": password,
        "imap_host": imap_host,
        "imap_port": imap_port,
    }, ""


def _verify_imap_login(store, user_email: str, imap_password: str) -> tuple[bool, str]:
    """Return (ok, error_message) after testing the password against connected accounts."""
    accounts = store.list_imap_accounts(user_email)
    if not accounts:
        return False, "No connected inbox accounts for this email."
    last_err = ""
    for account in accounts:
        ok, err = imap_service.test_connection(
            account["imap_host"],
            account["imap_port"],
            account["account_email"],
            imap_password,
        )
        if ok:
            return True, ""
        last_err = err
    return False, last_err or "IMAP verification failed."


def _is_production_app() -> bool:
    return os.environ.get("FLASK_ENV") == "production" or os.environ.get("ENV") == "production"


def _valid_email(email: str) -> bool:
    return "@" in email and "." in email.split("@")[-1]


def _generate_verification_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _parse_iso(ts: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _send_signup_code(user_email: str, code: str) -> tuple[bool, str, bool]:
    """Return (sent_ok, error_message, dev_code_shown)."""
    subject = "Your Inbox Tools verification code"
    body = (
        f"Your verification code is: {code}\n\n"
        "Enter this code on the signup page to finish creating your account. "
        "The code expires in 10 minutes.\n\n"
        "If you did not request this, you can ignore this email."
    )
    if mail.smtp_configured():
        ok, err = mail.send_email(user_email, subject, body)
        return ok, err, False

    if _is_production_app():
        return False, "Email verification is not configured. Contact the site administrator.", False

    # ponytail: dev-only — show code on screen when SMTP is unset so localhost signup still works.
    logger.info("Signup verification code for %s: %s (SMTP not configured)", user_email, code)
    return True, "", True


def _issue_verification_code(store, user_email: str) -> tuple[str | None, str, bool]:
    """Create a new code, persist it, and send. Return (code_or_none, error, dev_code_shown)."""
    existing = store.get_verification(user_email)
    now = _utcnow()
    if existing:
        last_sent = _parse_iso(existing["last_sent_at"])
        if now - last_sent < _RESEND_COOLDOWN:
            wait = int((_RESEND_COOLDOWN - (now - last_sent)).total_seconds())
            return None, f"Wait {max(wait, 1)} seconds before requesting another code.", False

    code = _generate_verification_code()
    code_hash = generate_password_hash(code, method="pbkdf2:sha256")
    expires_at = (now + _VERIFICATION_TTL).isoformat()
    store.create_verification(user_email, code_hash, expires_at, now.isoformat())

    sent_ok, err, dev_shown = _send_signup_code(user_email, code)
    if not sent_ok:
        store.delete_verification(user_email)
        return None, err, False
    return code if dev_shown else None, "", dev_shown


def _verify_signup_code(store, user_email: str, code: str) -> tuple[bool, str]:
    """Return (ok, error_message)."""
    row = store.get_verification(user_email)
    if row is None:
        return False, "No verification code on file. Request a new code."

    if row["attempt_count"] >= _MAX_VERIFICATION_ATTEMPTS:
        store.delete_verification(user_email)
        return False, "Too many incorrect attempts. Request a new code."

    expires = _parse_iso(row["expires_at"])
    if _utcnow() > expires:
        store.delete_verification(user_email)
        return False, "Verification code expired. Request a new code."

    if not check_password_hash(row["code_hash"], code.strip()):
        attempts = store.bump_verification_attempts(user_email)
        remaining = _MAX_VERIFICATION_ATTEMPTS - attempts
        if remaining <= 0:
            store.delete_verification(user_email)
            return False, "Too many incorrect attempts. Request a new code."
        return False, f"Incorrect code. {remaining} attempt(s) remaining."

    return True, ""


def _mailto_draft(email: dict, draft: str) -> str:
    sender = email.get("sender") or ""
    subject = email.get("subject") or ""
    return f"mailto:{quote(sender)}?subject={quote('Re: ' + subject)}&body={quote(draft)}"


def _invalidate_needs_reply_cache() -> None:
    if has_request_context():
        session.pop("needs_reply_cache", None)


def _groq_model_cache_key(api_key: str) -> str:
    fingerprint = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    return f"groq_model_{fingerprint}"


def get_store():
    return current_app.extensions["email_store"]


def get_credential_key() -> str:
    return current_app.config["CREDENTIAL_ENCRYPTION_KEY"]


def get_groq_client(user_email: str = "") -> GroqClient:
    email = user_email or getattr(g, "current_user_email", "")
    user_api_key = ""
    if email:
        try:
            stored = get_store().get_setting(email, "groq_api_key")
            if stored:
                user_api_key, _ = crypto.decrypt_with_fallback(
                    stored, _credential_keys(), purpose="groq"
                )
        except Exception:
            pass
    api_key = user_api_key or current_app.config.get("GROQ_API_KEY", "")
    client = GroqClient(
        api_key=api_key,
        default_model=current_app.config.get("GROQ_DEFAULT_MODEL", DEFAULT_CHAT_MODEL),
    )
    if api_key:
        cache_key = _groq_model_cache_key(api_key)
        cached = current_app.extensions.get(cache_key)
        if cached:
            client._cached_best_model = cached
    return client


def _cache_groq_model(client: GroqClient) -> None:
    if client.enabled and client._cached_best_model:
        current_app.extensions[_groq_model_cache_key(client.api_key)] = client._cached_best_model


def require_login():
    if not getattr(g, "current_user_email", ""):
        flash("Log in with your email to access your inbox tools.", "error")
        return redirect(url_for("main.login"))
    return None


def require_login_api():
    if not getattr(g, "current_user_email", ""):
        return jsonify({"error": "authentication required"}), 401
    return None


def _parse_sync_max(raw: str | int | None, default: int = 200) -> int:
    try:
        return max(1, min(int(raw or default), 2000))
    except (TypeError, ValueError):
        return default


def _default_sync_since() -> str:
    return (_utcnow() - datetime.timedelta(days=90)).date().isoformat()


def _parse_since_date(since_str: str | None) -> datetime.date | None:
    if not since_str:
        return None
    try:
        return datetime.date.fromisoformat(since_str.strip())
    except ValueError:
        return None


def _credential_keys() -> list[str]:
    """Current and legacy secrets so IMAP passwords survive a key change."""
    keys: list[str] = []
    primary = get_credential_key()
    if primary:
        keys.append(primary)
    secret = current_app.config.get("SECRET_KEY") or ""
    if secret and secret not in keys:
        keys.append(secret)
    key_file = Path(current_app.instance_path) / "secret_key"
    if key_file.is_file():
        try:
            file_key = key_file.read_text(encoding="utf-8").strip()
        except OSError:
            file_key = ""
        if file_key and file_key not in keys:
            keys.append(file_key)
    return keys


def _imap_password_for_account(store, account: dict) -> tuple[str, str | None]:
    """Return (plaintext_password, error). Re-encrypts if a fallback key worked."""
    ciphertext = account.get("encrypted_password") or ""
    plaintext, used_key = crypto.decrypt_with_fallback(
        ciphertext, _credential_keys(), purpose="imap"
    )
    if not plaintext:
        return "", (
            f"{account['account_email']}: could not decrypt the saved App Password. "
            "Update it on Accounts — you do not need to delete the mailbox."
        )
    primary = get_credential_key()
    if used_key and used_key != primary:
        store.update_imap_password(
            account["id"],
            account.get("user_email") or "",
            crypto.encrypt(plaintext, primary, purpose="imap"),
        )
    return plaintext, None


def _queue_job(
    user_email: str,
    job_type: str,
    label: str,
    account_ids: list[int] | None = None,
) -> tuple[str | None, str]:
    """Enqueue a background job. Return (job_id, error_if_blocked)."""
    store = get_store()
    active = store.get_active_job(user_email)
    if active:
        return None, "A job is already running — watch the activity panel."
    job_id = store.create_job(user_email, job_type, label)
    store.append_job_log(job_id, f"Queued: {label}")
    sync_worker.enqueue_job(job_id, job_type, user_email, account_ids)
    return job_id, ""


def _enrich_imap_accounts(store, accounts: list[dict]) -> list[dict]:
    enriched: list[dict] = []
    for acct in accounts:
        row = dict(acct)
        row["has_older_mail"] = store.account_has_older_mail(acct["id"])
        _, decrypt_err = _imap_password_for_account(store, acct)
        row["needs_reauth"] = bool(decrypt_err)
        enriched.append(row)
    return enriched


def sync_one_account(
    store,
    account: dict,
    user_email: str,
    groq_client: GroqClient,
    limit: int | None = None,
    since_date: datetime.date | None = None,
    backfill_only: bool = False,
    on_progress: Callable[..., None] | None = None,
) -> tuple[int, str | None]:
    """Fetch and upsert one account. Heuristic summaries only — AI runs after sync."""
    del groq_client  # IMAP ingest stays fast; Groq runs in the analyze phase.

    def log(message: str, current: int | None = None, total: int | None = None) -> None:
        if on_progress:
            on_progress(message, current, total)

    password, decrypt_err = _imap_password_for_account(store, account)
    if decrypt_err:
        return 0, decrypt_err

    sync_max = _parse_sync_max(limit or account.get("sync_max_count"))
    since_str = account.get("sync_since_date")
    if since_date is None:
        since_date = _parse_since_date(since_str)
    if since_date is None and not backfill_only:
        since_date = _parse_since_date(_default_sync_since())

    folders = store.get_enabled_folders(account["id"])
    total_imported = 0
    inbox_last_uid = account.get("last_uid") or 0
    inbox_backfill = account.get("backfill_uid") or 0
    inbox_uidvalidity = account.get("uidvalidity") or 0

    log(f"Connecting to {account['imap_host']} as {account['account_email']}…")
    for folder in folders:
        log(f"Fetching {folder} (since {since_date or 'cursor'}, max {sync_max})…")
        folder_state = store.get_folder_sync(account["id"], folder)
        since_uid = (folder_state or {}).get("last_uid", account.get("last_uid") or 0)
        backfill_uid = (folder_state or {}).get("backfill_uid", account.get("backfill_uid") or 0)
        stored_uidvalidity = (folder_state or {}).get("uidvalidity", account.get("uidvalidity") or 0)

        emails_raw, last_uid, new_backfill, uidvalidity = imap_service.fetch_emails(
            host=account["imap_host"],
            port=account["imap_port"],
            username=account["account_email"],
            password=password,
            folder=folder,
            since_uid=since_uid,
            backfill_uid=backfill_uid,
            stored_uidvalidity=stored_uidvalidity,
            limit=sync_max,
            since_date=since_date,
            backfill_only=backfill_only,
        )
        log(f"{folder}: downloaded {len(emails_raw)} message(s).")
        records = [
            build_email_record(
                msg,
                source_name=account["account_email"],
                user_email=user_email,
                source_account=account["account_email"],
                groq_client=None,
            )
            for msg in emails_raw
        ]
        total_imported += store.bulk_upsert(records)
        store.update_folder_sync(account["id"], folder, last_uid, new_backfill, uidvalidity)
        if folder.upper() == "INBOX":
            inbox_last_uid = last_uid
            inbox_backfill = new_backfill
            inbox_uidvalidity = uidvalidity
        log(f"{folder}: saved {len(records)}.")

    store.update_imap_last_sync(
        account["id"],
        inbox_last_uid,
        backfill_uid=inbox_backfill,
        uidvalidity=inbox_uidvalidity,
    )
    _invalidate_needs_reply_cache()
    return total_imported, None


def analyze_pending_emails(
    store,
    user_email: str,
    groq: GroqClient,
    on_progress: Callable[..., None],
    limit: int = 400,
) -> int:
    """Write Groq summaries for unanalyzed mail. Return how many succeeded."""
    emails = store.list_unanalyzed_emails(user_email, limit)
    if not emails:
        on_progress("All cached emails already have AI summaries.")
        return 0
    if not groq.enabled:
        on_progress("Groq is not configured — skipped AI analysis.")
        return 0

    total = len(emails)
    model_name = groq.select_max_context_model()
    on_progress(f"Using Groq model {model_name}…", 0, total)
    _cache_groq_model(groq)
    analyzed = 0
    batch_size = 3
    for start in range(0, total, batch_size):
        check_cancelled(store)
        chunk = emails[start : start + batch_size]
        on_progress(
            f"AI summarizing {start + 1}–{min(start + batch_size, total)} of {total}…",
            start,
            total,
        )
        results = groq.summarize_emails_batch(chunk, batch_size=batch_size)
        if groq.last_model_used and groq.last_model_used != model_name:
            model_name = groq.last_model_used
            on_progress(f"Switched to Groq model {model_name}…")
        if not results and groq.last_error:
            on_progress(f"Groq error: {groq.last_error}")
            if is_fatal_groq_auth_error(groq.last_error):
                on_progress("Stopping analysis — Groq rejected this API key.")
                return analyzed
            if is_rate_limit_error(groq.last_error):
                on_progress("Rate limited — switching Groq model and retrying smaller requests.")
            if groq.last_error == "Cancelled.":
                raise JobCancelled()
        for email in chunk:
            bullets = results.get(email["email_id"])
            if not bullets:
                bullets = groq.summarize_email(
                    sender=email.get("sender") or "",
                    subject=email.get("subject") or "",
                    body=email.get("body") or "",
                )
                if groq.last_model_used and groq.last_model_used != model_name:
                    model_name = groq.last_model_used
                    on_progress(f"Switched to Groq model {model_name}…")
            if bullets:
                store.update_email_summary(email["email_id"], user_email, bullets)
                analyzed += 1
            elif groq.last_error and is_fatal_groq_auth_error(groq.last_error):
                on_progress(f"Groq error: {groq.last_error}")
                on_progress("Stopping analysis — Groq rejected this API key.")
                return analyzed
        _cache_groq_model(groq)
    if analyzed == 0 and groq.last_error:
        on_progress(f"No emails could be summarized. {groq.last_error}")
    else:
        on_progress(f"Summarized {analyzed} of {total}.", total, total)
    return analyzed


def refresh_cached_digest(store, user_email: str, groq: GroqClient | None) -> None:
    """Store an inbox brief so the dashboard does not wait on Groq."""
    emails = store.list_emails(limit=40, user_email=user_email)
    accounts = store.list_imap_accounts(user_email)
    digest = build_digest(
        emails,
        has_imap_accounts=bool(accounts),
        groq_client=groq,
    )
    store.set_kv(user_email, "inbox_digest", json.dumps(digest))
    if groq is not None and groq.enabled:
        _cache_groq_model(groq)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user_email = (request.form.get("email") or "").strip().lower()
        if not _valid_email(user_email):
            flash("Enter a valid email address.", "error")
            return render_template("login.html")

        store = get_store()
        stored_hash = store.get_app_password_hash(user_email)
        app_pw = (request.form.get("app_password") or "").strip()
        new_pw = (request.form.get("new_app_password") or "").strip()
        confirm_pw = (request.form.get("confirm_app_password") or "").strip()

        if stored_hash:
            if not app_pw:
                flash("This account has a password set. Enter it to log in.", "error")
                return render_template("login.html", needs_app_password=True, prefill_email=user_email)
            if not check_password_hash(stored_hash, app_pw):
                flash("Incorrect account password.", "error")
                return render_template("login.html", needs_app_password=True, prefill_email=user_email)
            session["user_email"] = user_email
            flash("Logged in successfully.", "success")
            return redirect(url_for("main.inbox"))

        imap_accounts = store.list_imap_accounts(user_email)
        imap_pw = (request.form.get("imap_password") or "").strip()

        if imap_accounts:
            if not imap_pw:
                flash("This account uses IMAP sign-in. Enter your mailbox App Password.", "error")
                return render_template(
                    "login.html",
                    needs_imap_login=True,
                    prefill_email=user_email,
                )
            ok, err = _verify_imap_login(store, user_email, imap_pw)
            if not ok:
                flash(f"IMAP verification failed: {err}", "error")
                return render_template(
                    "login.html",
                    needs_imap_login=True,
                    prefill_email=user_email,
                )
            if new_pw:
                if len(new_pw) < 6:
                    flash("Password must be at least 6 characters.", "error")
                    return render_template(
                        "login.html",
                        needs_imap_login=True,
                        prefill_email=user_email,
                        show_set_password=True,
                    )
                if new_pw != confirm_pw:
                    flash("Passwords do not match.", "error")
                    return render_template(
                        "login.html",
                        needs_imap_login=True,
                        prefill_email=user_email,
                        show_set_password=True,
                    )
                store.set_app_password(user_email, generate_password_hash(new_pw, method="pbkdf2:sha256"))
            session["user_email"] = user_email
            flash("Logged in with IMAP verification.", "success")
            return redirect(url_for("main.inbox"))

        flash("No account found for this email. Create one first.", "error")
        return render_template("login.html", prefill_email=user_email)

    if getattr(g, "current_user_email", ""):
        return redirect(url_for("main.inbox"))

    return render_template("login.html")


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if getattr(g, "current_user_email", ""):
        return redirect(url_for("main.inbox"))

    store = get_store()
    step = "email"
    prefill_email = (session.get("pending_signup_email") or "").strip().lower()
    dev_code: str | None = None

    if request.method == "POST":
        action = (request.form.get("action") or "send_code").strip()
        user_email = (request.form.get("email") or prefill_email or "").strip().lower()

        if action == "resend_code":
            if not _valid_email(user_email):
                flash("Enter a valid email address.", "error")
                return render_template("signup.html", step="email")
            if store.get_app_password_hash(user_email):
                flash("An account already exists for this email. Log in instead.", "error")
                return redirect(url_for("main.login"))
            dev_code, err, dev_shown = _issue_verification_code(store, user_email)
            if err:
                flash(err, "error")
            else:
                session["pending_signup_email"] = user_email
                flash("A new verification code was sent.", "success")
                if dev_shown and dev_code:
                    flash(f"Development mode — your code is {dev_code}", "success")
            return render_template(
                "signup.html",
                step="verify",
                prefill_email=user_email,
                dev_code=dev_code if dev_shown else None,
            )

        if action == "send_code":
            if not _valid_email(user_email):
                flash("Enter a valid email address.", "error")
                return render_template("signup.html", step="email")
            if store.get_app_password_hash(user_email):
                flash("An account already exists for this email. Log in instead.", "error")
                return redirect(url_for("main.login"))
            dev_code, err, dev_shown = _issue_verification_code(store, user_email)
            if err:
                flash(err, "error")
                return render_template("signup.html", step="email", prefill_email=user_email)
            session["pending_signup_email"] = user_email
            flash("Check your email for a 6-digit verification code.", "success")
            if dev_shown and dev_code:
                flash(f"Development mode — your code is {dev_code}", "success")
            return render_template(
                "signup.html",
                step="verify",
                prefill_email=user_email,
                dev_code=dev_code if dev_shown else None,
            )

        if action == "confirm":
            user_email = (user_email or session.get("pending_signup_email") or "").strip().lower()
            code = (request.form.get("verification_code") or "").strip()
            new_pw = (request.form.get("new_app_password") or "").strip()
            confirm_pw = (request.form.get("confirm_app_password") or "").strip()

            if not _valid_email(user_email):
                flash("Enter a valid email address.", "error")
                return render_template("signup.html", step="email")
            if store.get_app_password_hash(user_email):
                flash("An account already exists for this email. Log in instead.", "error")
                return redirect(url_for("main.login"))
            if not code:
                flash("Enter the 6-digit verification code from your email.", "error")
                return render_template("signup.html", step="verify", prefill_email=user_email)
            if len(new_pw) < 6:
                flash("Password must be at least 6 characters.", "error")
                return render_template("signup.html", step="verify", prefill_email=user_email)
            if new_pw != confirm_pw:
                flash("Passwords do not match.", "error")
                return render_template("signup.html", step="verify", prefill_email=user_email)

            ok, err = _verify_signup_code(store, user_email, code)
            if not ok:
                flash(err, "error")
                return render_template("signup.html", step="verify", prefill_email=user_email)

            store.set_app_password(user_email, generate_password_hash(new_pw, method="pbkdf2:sha256"))
            store.delete_verification(user_email)
            session.pop("pending_signup_email", None)
            session["user_email"] = user_email
            flash("Account created. Connect your inbox next.", "success")
            return redirect(url_for("main.accounts_add"))

    if prefill_email and store.get_verification(prefill_email):
        step = "verify"

    return render_template("signup.html", step=step, prefill_email=prefill_email, dev_code=dev_code)


@bp.get("/help")
def help_page():
    return render_template("help.html")


@bp.post("/logout")
def logout():
    session.pop("user_email", None)
    session.pop("needs_reply_cache", None)
    flash("You have been logged out.", "success")
    return redirect(url_for("main.login"))


@bp.get("/")
def index():
    if getattr(g, "current_user_email", ""):
        return redirect(url_for("main.inbox"))
    return redirect(url_for("main.login"))


@bp.get("/dashboard")
def dashboard():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    user_email = g.current_user_email
    source_account = request.args.get("source_account") or None

    stats = store.get_stats(user_email=user_email, source_account=source_account)
    categories = store.get_categories(user_email=user_email, source_account=source_account)
    imap_accounts = store.list_imap_accounts(user_email)
    recent_unread = store.list_emails(
        limit=20,
        user_email=user_email,
        only_unread=True,
        source_account=source_account,
        sort="date_desc",
    )
    urgent_emails = store.list_emails(
        limit=15,
        user_email=user_email,
        source_account=source_account,
        sort="priority",
    )
    urgent_emails = [e for e in urgent_emails if e["priority_score"] >= 75]
    cached_emails = store.list_emails(limit=50, user_email=user_email, source_account=source_account)
    groq = get_groq_client(user_email)
    digest = None
    cached_digest = store.get_kv(user_email, "inbox_digest")
    if cached_digest:
        try:
            parsed = json.loads(cached_digest)
            if isinstance(parsed, dict) and parsed.get("headline"):
                digest = parsed
        except (TypeError, ValueError):
            digest = None
    if digest is None:
        digest = build_digest(
            cached_emails,
            has_imap_accounts=bool(imap_accounts),
            groq_client=None,
        )
    important_emails = build_important_items(cached_emails)
    ai_analyzed, ai_pending = store.count_ai_stats(user_email)
    if groq.enabled and ai_pending > 0 and store.get_active_job(user_email) is None:
        _queue_job(user_email, "reanalyze", f"Analyze {ai_pending} email(s) with AI")

    return render_template(
        "dashboard.html",
        stats=stats,
        categories=categories,
        digest=digest,
        imap_accounts=_enrich_imap_accounts(store, imap_accounts),
        source_account=source_account,
        recent_unread=recent_unread,
        urgent_emails=urgent_emails,
        important_emails=important_emails,
        default_sync_since=_default_sync_since(),
        default_sync_max=200,
        groq_available=groq.enabled,
        ai_analyzed=ai_analyzed,
        ai_pending=ai_pending,
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
    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])

    for file in files:
        safe_name = secure_filename(file.filename or "")
        if not safe_name or safe_name in (".", "..") or "/" in safe_name or "\\" in safe_name:
            flash(f"Skipped invalid filename: {file.filename}", "error")
            continue

        upload_path = upload_folder / f"{uuid.uuid4().hex}_{safe_name}"
        file.save(upload_path)
        try:
            parsed_messages = parse_email_upload(upload_path)
            records = [
                build_email_record(
                    message,
                    safe_name,
                    user_email=user_email,
                    groq_client=groq_client,
                )
                for message in parsed_messages
            ]
            imported_count += store.bulk_upsert(records)
        except ValueError as exc:
            flash(str(exc), "error")
        finally:
            upload_path.unlink(missing_ok=True)

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

    store = get_store()
    user_email = g.current_user_email
    email = store.get_email(email_id, user_email=user_email)
    if email is None:
        flash("That email could not be found.", "error")
        return redirect(url_for("main.inbox"))

    groq = get_groq_client()
    auto_analyzed = False
    if groq.enabled and not email.get("ai_analyzed"):
        bullets = groq.summarize_email(
            sender=email["sender"],
            subject=email["subject"],
            body=email["body"],
        )
        if bullets:
            store.update_email_summary(email_id, user_email, bullets)
            email["bullet_summary"] = bullets
            email["ai_analyzed"] = 1
            auto_analyzed = True

    tags = store.get_email_tags(email_id)
    all_tags = store.list_tags(user_email)
    assigned_tag_ids = {t["id"] for t in tags}
    thread_emails = store.list_thread_emails(email.get("thread_id", ""), user_email)
    draft_reply = None
    if groq.enabled and request.args.get("draft") == "1":
        draft_reply = groq.draft_reply(
            sender=email["sender"],
            subject=email["subject"],
            body=email["body"],
        )
        _cache_groq_model(groq)
    if not email.get("is_read"):
        store.set_email_read(email_id, user_email, True)
    return render_template(
        "email_detail.html",
        email=email,
        groq_available=groq.enabled,
        auto_analyzed=auto_analyzed,
        tags=tags,
        all_tags=all_tags,
        assigned_tag_ids=assigned_tag_ids,
        thread_emails=thread_emails,
        draft_reply=draft_reply,
        mailto_link=_mailto_draft(email, draft_reply) if draft_reply else "",
    )


@bp.post("/email/<email_id>/tags")
def email_set_tags(email_id: str):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    if store.get_email(email_id, user_email=g.current_user_email) is None:
        flash("Email not found.", "error")
        return redirect(url_for("main.inbox"))

    tag_ids = [int(tid) for tid in request.form.getlist("tag_ids") if tid.isdigit()]
    store.set_email_tags(email_id, tag_ids)
    flash("Tags updated.", "success")
    return redirect(request.referrer or url_for("main.email_detail", email_id=email_id))


@bp.post("/email/<email_id>/read")
def email_mark_read(email_id: str):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect
    read = request.form.get("read", "1") == "1"
    get_store().set_email_read(email_id, g.current_user_email, read)
    return redirect(request.referrer or url_for("main.inbox"))


@bp.post("/email/<email_id>/reanalyze")
def email_reanalyze(email_id: str):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    email = store.get_email(email_id, user_email=g.current_user_email)
    if email is None:
        flash("Email not found.", "error")
        return redirect(url_for("main.inbox"))

    groq = get_groq_client()
    if not groq.enabled:
        flash("Add a Groq API key in Settings to enable AI analysis.", "error")
        return redirect(url_for("main.email_detail", email_id=email_id))

    bullets = groq.summarize_email(
        sender=email["sender"],
        subject=email["subject"],
        body=email["body"],
    )
    if bullets:
        store.update_email_summary(email_id, g.current_user_email, bullets)
        flash("AI analysis updated.", "success")
    else:
        flash("AI analysis failed — check your Groq key in Settings.", "error")
    return redirect(url_for("main.email_detail", email_id=email_id))


@bp.post("/email/<email_id>/hide")
def email_hide(email_id: str):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect
    get_store().set_email_hidden(email_id, g.current_user_email, True)
    flash("Email hidden.", "success")
    return redirect(request.referrer or url_for("main.inbox"))


@bp.post("/email/<email_id>/unhide")
def email_unhide(email_id: str):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect
    get_store().set_email_hidden(email_id, g.current_user_email, False)
    flash("Email restored to inbox.", "success")
    return redirect(request.referrer or url_for("main.hidden"))


@bp.post("/inbox/bulk-hide")
def inbox_bulk_hide():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect
    store = get_store()
    user_email = g.current_user_email
    hidden_ids = []
    for email_id in request.form.getlist("email_ids"):
        store.set_email_hidden(email_id, user_email, True)
        hidden_ids.append(email_id)
    if hidden_ids:
        session["bulk_undo_ids"] = hidden_ids
    flash("Selected emails hidden.", "success")
    return redirect(request.referrer or url_for("main.inbox"))


@bp.post("/inbox/bulk-unhide")
def inbox_bulk_unhide():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect
    store = get_store()
    user_email = g.current_user_email
    for email_id in request.form.getlist("email_ids"):
        store.set_email_hidden(email_id, user_email, False)
    flash("Selected emails restored.", "success")
    return redirect(request.referrer or url_for("main.inbox"))


@bp.post("/inbox/bulk-read")
def inbox_bulk_read():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect
    store = get_store()
    user_email = g.current_user_email
    read = request.form.get("read", "1") == "1"
    for email_id in request.form.getlist("email_ids"):
        store.set_email_read(email_id, user_email, read)
    flash("Selected emails marked " + ("read." if read else "unread."), "success")
    return redirect(request.referrer or url_for("main.inbox"))


@bp.post("/email/<email_id>/draft-reply")
def email_draft_reply(email_id: str):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    user_email = g.current_user_email
    email = store.get_email(email_id, user_email=user_email)
    if email is None:
        flash("Email not found.", "error")
        return redirect(url_for("main.inbox"))

    groq = get_groq_client()
    if not groq.enabled:
        flash("Add a Groq API key in Settings to draft replies.", "error")
        return redirect(url_for("main.email_detail", email_id=email_id))

    reason = (request.form.get("reason") or "").strip()
    draft = groq.draft_reply(
        sender=email["sender"],
        subject=email["subject"],
        body=email["body"],
        reason=reason,
    )
    _cache_groq_model(groq)
    if not draft:
        flash("Could not generate a draft reply.", "error")
        return redirect(url_for("main.email_detail", email_id=email_id))

    return render_template(
        "email_detail.html",
        email=email,
        groq_available=True,
        auto_analyzed=False,
        tags=store.get_email_tags(email_id),
        all_tags=store.list_tags(user_email),
        assigned_tag_ids={t["id"] for t in store.get_email_tags(email_id)},
        thread_emails=store.list_thread_emails(email.get("thread_id", ""), user_email),
        draft_reply=draft,
        mailto_link=_mailto_draft(email, draft),
    )


@bp.route("/accounts", methods=["GET"])
def accounts():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    imap_accounts = store.list_imap_accounts(g.current_user_email)
    enriched = []
    for acct in imap_accounts:
        row = dict(acct)
        row["folder_sync"] = store.list_folder_sync(acct["id"])
        row["has_older_mail"] = store.account_has_older_mail(acct["id"])
        _, decrypt_err = _imap_password_for_account(store, acct)
        row["needs_reauth"] = bool(decrypt_err)
        enriched.append(row)
    return render_template(
        "accounts.html",
        imap_accounts=enriched,
        default_sync_since=_default_sync_since(),
        default_sync_max=200,
    )


@bp.route("/accounts/add", methods=["GET", "POST"])
def accounts_add():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    user_email = g.current_user_email

    if request.method == "POST":
        parsed, form_err = _parse_imap_form()
        if parsed is None:
            flash(form_err, "error")
            return render_template(
                "accounts.html",
                imap_accounts=store.list_imap_accounts(user_email),
                show_add_form=True,
            )
        account_email = parsed["account_email"]
        password = parsed["password"]
        imap_host = parsed["imap_host"]
        imap_port = parsed["imap_port"]

        ok, err = imap_service.test_connection(imap_host, imap_port, account_email, password)
        if not ok:
            flash(f"Could not connect to {imap_host}: {err}", "error")
            return render_template(
                "accounts.html",
                imap_accounts=store.list_imap_accounts(user_email),
                show_add_form=True,
            )

        encrypted = crypto.encrypt(password, get_credential_key(), purpose="imap")
        account_id = store.save_imap_account(
            user_email=user_email,
            account_email=account_email,
            imap_host=imap_host,
            imap_port=imap_port,
            encrypted_password=encrypted,
        )
        store.update_imap_sync_prefs(account_id, _default_sync_since(), 200)
        try:
            remote_folders = imap_service.list_folders(imap_host, imap_port, account_email, password)
            store.ensure_folder_sync_rows(account_id, remote_folders)
        except Exception:
            store.ensure_folder_sync_rows(account_id, ["INBOX"])

        try:
            job_id, queue_err = _queue_job(
                user_email,
                "sync",
                f"Initial sync {account_email}",
                account_ids=[account_id],
            )
            if queue_err:
                flash(f"Account {account_email} connected. {queue_err}", "success")
            else:
                flash(
                    f"Account {account_email} connected. Fetching recent mail in the background — watch the activity panel.",
                    "success",
                )
        except Exception as exc:
            flash(f"Account connected. Could not start sync: {exc}", "error")

        return redirect(url_for("main.accounts"))

    return render_template(
        "accounts.html",
        imap_accounts=store.list_imap_accounts(user_email),
        show_add_form=True,
    )


@bp.post("/accounts/delete/<int:account_id>")
def accounts_delete(account_id: int):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    get_store().delete_imap_account(account_id, g.current_user_email)
    flash("Account removed.", "success")
    return redirect(url_for("main.accounts"))


@bp.post("/accounts/sync-all")
def accounts_sync_all():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    accounts = store.list_imap_accounts(g.current_user_email)
    if not accounts:
        flash("No accounts to sync.", "error")
        return redirect(url_for("main.accounts"))

    job_id, queue_err = _queue_job(
        g.current_user_email,
        "sync",
        f"Sync {len(accounts)} account(s)",
    )
    if queue_err:
        flash(queue_err, "error")
    else:
        flash("Sync started — watch the activity panel for progress.", "success")
    return redirect(request.referrer or url_for("main.accounts"))


@bp.post("/accounts/sync/<int:account_id>")
def accounts_sync(account_id: int):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    user_email = g.current_user_email
    account = store.get_imap_account(account_id, user_email)
    if account is None:
        flash("Account not found.", "error")
        return redirect(url_for("main.accounts"))

    since = (request.form.get("sync_since") or "").strip() or _default_sync_since()
    sync_max = _parse_sync_max(request.form.get("sync_max") or account.get("sync_max_count"))
    store.update_imap_sync_prefs(account_id, since, sync_max)
    account = store.get_imap_account(account_id, user_email)
    if account is None:
        return redirect(url_for("main.accounts"))

    folder_names = request.form.getlist("folders")
    if folder_names:
        for row in store.list_folder_sync(account_id):
            store.set_folder_enabled(account_id, row["folder"], row["folder"] in folder_names)

    job_id, queue_err = _queue_job(
        user_email,
        "sync",
        f"Sync {account['account_email']}",
        account_ids=[account_id],
    )
    if queue_err:
        flash(queue_err, "error")
    else:
        flash(
            f"Sync started for {account['account_email']}. Mail appears first, then AI summaries run automatically.",
            "success",
        )
    return redirect(request.referrer or url_for("main.accounts"))


@bp.post("/accounts/load-older/<int:account_id>")
def accounts_load_older(account_id: int):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    user_email = g.current_user_email
    account = store.get_imap_account(account_id, user_email)
    if account is None:
        flash("Account not found.", "error")
        return redirect(url_for("main.accounts"))

    since = (request.form.get("sync_since") or account.get("sync_since_date") or _default_sync_since()).strip()
    sync_max = _parse_sync_max(request.form.get("sync_max") or account.get("sync_max_count"))
    store.update_imap_sync_prefs(account_id, since, sync_max)
    account = store.get_imap_account(account_id, user_email)
    if account is None:
        return redirect(url_for("main.accounts"))

    if not store.account_has_older_mail(account_id):
        flash("No older mail pending for this account.", "error")
        return redirect(request.referrer or url_for("main.accounts"))

    job_id, queue_err = _queue_job(
        user_email,
        "backfill",
        f"Load older mail for {account['account_email']}",
        account_ids=[account_id],
    )
    if queue_err:
        flash(queue_err, "error")
    else:
        flash("Loading older mail in the background — watch the activity panel.", "success")
    return redirect(request.referrer or url_for("main.dashboard"))


@bp.post("/accounts/<int:account_id>/folders")
def accounts_update_folders(account_id: int):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    account = store.get_imap_account(account_id, g.current_user_email)
    if account is None:
        flash("Account not found.", "error")
        return redirect(url_for("main.accounts"))

    enabled = set(request.form.getlist("folders"))
    for row in store.list_folder_sync(account_id):
        store.set_folder_enabled(account_id, row["folder"], row["folder"] in enabled)
    flash("Folder selection updated.", "success")
    return redirect(url_for("main.accounts"))


@bp.get("/search")
def search_page():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    query = request.args.get("query", "").strip()
    sender_filter = request.args.get("from_", "").strip()
    recipient_filter = request.args.get("to_", "").strip()
    subject_filter = request.args.get("subject_", "").strip()
    category = request.args.get("category") or None
    source_account = request.args.get("source_account") or None
    date_from = request.args.get("date_from", "").strip() or None
    date_to = request.args.get("date_to", "").strip() or None
    tag_filter_raw = request.args.get("tag_id", "").strip()
    tag_filter = int(tag_filter_raw) if tag_filter_raw.isdigit() else None
    ai_mode = request.args.get("ai") == "1"
    user_email = g.current_user_email

    emails: list = []
    ai_answer: str | None = None
    ai_no_candidates = False
    searched = bool(
        query or sender_filter or recipient_filter or subject_filter
        or category or date_from or date_to or tag_filter
    )

    common_kwargs = dict(
        user_email=user_email,
        source_account=source_account,
        sender_filter=sender_filter or None,
        recipient_filter=recipient_filter or None,
        subject_filter=subject_filter or None,
        category=category,
        date_from=date_from,
        date_to=date_to,
        tag_filter=tag_filter,
    )

    if searched:
        if query:
            emails = store.search(query, **common_kwargs)
        else:
            emails = store.list_emails(**common_kwargs)

        if ai_mode and query:
            if not emails:
                ai_no_candidates = True
            else:
                groq = get_groq_client()
                if groq.enabled:
                    ai_answer = groq.answer_about_emails(query, emails)
                    if ai_answer is None:
                        flash("AI search failed — check your Groq key.", "error")
                else:
                    flash("Add a Groq API key in Settings to use AI search.", "error")

    categories = store.get_categories(user_email=user_email)
    tags = store.list_tags(user_email)
    groq_available = get_groq_client().enabled
    return render_template(
        "search.html",
        emails=emails,
        query=query,
        sender_filter=sender_filter,
        recipient_filter=recipient_filter,
        subject_filter=subject_filter,
        selected_category=category,
        categories=categories,
        source_account=source_account,
        ai_mode=ai_mode,
        ai_answer=ai_answer,
        ai_no_candidates=ai_no_candidates,
        searched=searched,
        groq_available=groq_available,
        date_from=date_from or "",
        date_to=date_to or "",
        tags=tags,
        selected_tag=tag_filter,
    )


@bp.post("/search/save-tag")
def search_save_tag():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    user_email = g.current_user_email
    name = (request.form.get("tag_name") or "").strip()
    if not name:
        flash("Tag name is required.", "error")
        return redirect(url_for("main.search_page"))

    tag_id = store.save_tag(user_email, name, "#2d8f85", False, "", False)
    query = (request.form.get("query") or "").strip()
    sender = (request.form.get("from_") or "").strip()
    subject = (request.form.get("subject_") or "").strip()
    if query:
        store.save_tag_rule(tag_id, "body", "contains", query)
    if sender:
        store.save_tag_rule(tag_id, "sender", "contains", sender)
    if subject:
        store.save_tag_rule(tag_id, "subject", "contains", subject)
    flash(f"Tag '{name}' created with filter rules from your search.", "success")
    return redirect(url_for("main.search_page", tag_id=tag_id))


@bp.get("/inbox")
def inbox():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    source_account = request.args.get("source_account") or None
    query = request.args.get("query", "").strip()
    category = request.args.get("category") or None
    date_from = request.args.get("date_from", "").strip() or None
    date_to = request.args.get("date_to", "").strip() or None
    tag_filter_raw = request.args.get("tag_id", "").strip()
    tag_filter = int(tag_filter_raw) if tag_filter_raw.isdigit() else None
    sort = request.args.get("sort", "date_desc")
    if sort not in ("date_desc", "date_asc", "priority"):
        sort = "date_desc"
    only_unread = request.args.get("unread") == "1"
    exclude_mailing_list = request.args.get("no_lists") == "1"
    limit_raw = request.args.get("limit", "100")
    limit = int(limit_raw) if limit_raw.isdigit() and 1 <= int(limit_raw) <= 500 else 100
    offset_raw = request.args.get("offset", "0")
    offset = int(offset_raw) if offset_raw.isdigit() and int(offset_raw) >= 0 else 0
    selected_email_id = request.args.get("email_id") or None
    user_email = g.current_user_email

    common_kwargs = dict(
        user_email=user_email,
        source_account=source_account,
        category=category,
        date_from=date_from,
        date_to=date_to,
        tag_filter=tag_filter,
        sort=sort,
        only_unread=only_unread,
        exclude_mailing_list=exclude_mailing_list,
    )

    if query:
        emails = store.search(query, limit=limit, offset=offset, **common_kwargs)
        total_count = store.count_emails(search_term=query, **{k: v for k, v in common_kwargs.items() if k != "sort"})
    else:
        emails = store.list_emails(limit=limit, offset=offset, **common_kwargs)
        total_count = store.count_emails(**{k: v for k, v in common_kwargs.items() if k != "sort"})

    thread_counts: dict[str, int] = {}
    for email in emails:
        tid = email.get("thread_id") or ""
        if tid:
            thread_counts[tid] = thread_counts.get(tid, 0) + 1

    selected_email = None
    if selected_email_id:
        selected_email = store.get_email(selected_email_id, user_email=user_email)
    elif emails and request.args.get("pane") == "1":
        selected_email = emails[0]

    prev_offset = max(0, offset - limit)
    next_offset = offset + limit if offset + limit < total_count else None

    imap_accounts = store.list_imap_accounts(user_email)
    categories = store.get_categories(user_email=user_email, source_account=source_account)
    tags = store.list_tags(user_email)
    hidden_count = len(store.list_emails(user_email=user_email, only_hidden=True, exclude_hidden=False, limit=1000))
    unread_count = len(store.list_emails(user_email=user_email, only_unread=True, limit=500))
    email_tags_map = store.get_email_tags_batch([e["email_id"] for e in emails])

    return render_template(
        "inbox.html",
        emails=emails,
        imap_accounts=imap_accounts,
        categories=categories,
        source_account=source_account,
        selected_category=category,
        query=query,
        tags=tags,
        selected_tag=tag_filter,
        date_from=date_from or "",
        date_to=date_to or "",
        hidden_count=hidden_count,
        unread_count=unread_count,
        sort=sort,
        only_unread=only_unread,
        exclude_mailing_list=exclude_mailing_list,
        limit=limit,
        offset=offset,
        total_count=total_count,
        prev_offset=prev_offset,
        next_offset=next_offset,
        selected_email=selected_email,
        selected_email_id=selected_email_id,
        thread_counts=thread_counts,
        split_pane=request.args.get("pane") == "1",
        bulk_undo_ids=session.pop("bulk_undo_ids", None),
        email_tags_map=email_tags_map,
        all_tags=tags,
        groq_available=get_groq_client(user_email).enabled,
        ai_pending=store.count_ai_stats(user_email)[1],
    )


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    user_email = g.current_user_email

    if request.method == "POST":
        action = request.form.get("action", "save_groq")

        if action == "set_app_password":
            new_pw = (request.form.get("new_app_password") or "").strip()
            confirm_pw = (request.form.get("confirm_app_password") or "").strip()
            if not new_pw:
                flash("Enter a password to set.", "error")
            elif new_pw != confirm_pw:
                flash("Passwords do not match.", "error")
            elif len(new_pw) < 6:
                flash("Password must be at least 6 characters.", "error")
            else:
                store.set_app_password(user_email, generate_password_hash(new_pw, method="pbkdf2:sha256"))
                flash("Account password set. You'll need it the next time you log in.", "success")
            return redirect(url_for("main.settings"))

        if action == "remove_app_password":
            accounts = store.list_imap_accounts(user_email)
            if not accounts:
                flash("Connect an inbox account before removing your account password.", "error")
            else:
                store.set_app_password(user_email, "")
                flash("Account password removed. Next login requires your connected IMAP account.", "success")
            return redirect(url_for("main.settings"))

        if action == "clear_groq":
            store.save_setting(user_email, "groq_api_key", "")
            flash("Groq API key cleared.", "success")
            return redirect(url_for("main.settings"))

        if action == "reanalyze_unanalyzed":
            groq = get_groq_client(user_email)
            if not groq.enabled:
                flash("Add a Groq API key to re-analyze emails.", "error")
            else:
                pending = store.count_ai_stats(user_email)[1]
                job_id, queue_err = _queue_job(
                    user_email,
                    "reanalyze",
                    f"Analyze {pending} email(s) with AI",
                )
                if queue_err:
                    flash(queue_err, "error")
                else:
                    flash("AI analysis started — watch the activity panel.", "success")
            return redirect(url_for("main.settings"))

        groq_key = (request.form.get("groq_api_key") or "").strip()
        if groq_key:
            encrypted = crypto.encrypt(groq_key, get_credential_key(), purpose="groq")
            store.save_setting(user_email, "groq_api_key", encrypted)
            flash("Groq API key saved.", "success")
        else:
            flash("Settings saved (Groq key unchanged).", "success")
        return redirect(url_for("main.settings"))

    has_groq_key = bool(store.get_setting(user_email, "groq_api_key"))
    active_model = current_app.config.get("GROQ_DEFAULT_MODEL", DEFAULT_CHAT_MODEL)
    has_app_password = bool(store.get_app_password_hash(user_email))
    ai_analyzed, ai_pending = store.count_ai_stats(user_email)
    return render_template(
        "settings.html",
        has_groq_key=has_groq_key,
        active_model=active_model,
        has_app_password=has_app_password,
        ai_analyzed=ai_analyzed,
        ai_pending=ai_pending,
        groq_available=get_groq_client(user_email).enabled,
    )


@bp.get("/api/senders")
def api_senders():
    auth = require_login_api()
    if auth is not None:
        return auth
    senders = get_store().get_senders(g.current_user_email)
    return jsonify(senders)


@bp.get("/api/jobs")
def api_jobs():
    auth = require_login_api()
    if auth is not None:
        return auth
    store = get_store()
    user_email = g.current_user_email
    groq = get_groq_client(user_email)
    analyzed, pending = store.count_ai_stats(user_email)
    return jsonify(
        {
            "active": store.get_active_job(user_email),
            "latest": store.get_latest_job(user_email),
            "jobs": store.list_jobs(user_email, 5),
            "ai": {
                "analyzed": analyzed,
                "pending": pending,
                "groq_enabled": groq.enabled,
            },
        }
    )


@bp.post("/jobs/cancel")
def jobs_cancel():
    wants_json = "application/json" in (request.headers.get("Accept") or "")
    if wants_json:
        auth = require_login_api()
        if auth is not None:
            return auth
        cancelled = get_store().cancel_active_jobs(g.current_user_email)
        return jsonify({"ok": True, "cancelled": len(cancelled)})

    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect
    cancelled = get_store().cancel_active_jobs(g.current_user_email)
    if cancelled:
        flash("Job cancelled. You can start a new sync or analysis.", "success")
    else:
        flash("No running job to cancel.", "error")
    return redirect(request.referrer or url_for("main.inbox"))


@bp.post("/analyze")
def analyze_now():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    user_email = g.current_user_email
    groq = get_groq_client(user_email)
    if not groq.enabled:
        flash("Add a Groq API key in Settings to generate AI summaries.", "error")
        return redirect(url_for("main.settings"))

    pending = store.count_ai_stats(user_email)[1]
    if pending <= 0:
        flash("All cached emails already have AI summaries.", "success")
        return redirect(request.referrer or url_for("main.dashboard"))

    job_id, queue_err = _queue_job(
        user_email,
        "reanalyze",
        f"Analyze {pending} email(s) with AI",
    )
    if queue_err:
        flash(queue_err, "error")
    else:
        flash("AI analysis started — watch the activity panel for progress.", "success")
    return redirect(request.referrer or url_for("main.dashboard"))


@bp.post("/accounts/<int:account_id>/password")
def accounts_update_password(account_id: int):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    user_email = g.current_user_email
    account = store.get_imap_account(account_id, user_email)
    if account is None:
        flash("Account not found.", "error")
        return redirect(url_for("main.accounts"))

    password = (request.form.get("password") or "").strip()
    if not password:
        flash("Enter the mailbox App Password.", "error")
        return redirect(url_for("main.accounts"))

    ok, err = imap_service.test_connection(
        account["imap_host"],
        account["imap_port"],
        account["account_email"],
        password,
    )
    if not ok:
        flash(f"Could not connect: {err}", "error")
        return redirect(url_for("main.accounts"))

    encrypted = crypto.encrypt(password, get_credential_key(), purpose="imap")
    store.update_imap_password(account_id, user_email, encrypted)
    job_id, queue_err = _queue_job(
        user_email,
        "sync",
        f"Sync {account['account_email']}",
        account_ids=[account_id],
    )
    if queue_err:
        flash(f"App Password saved. {queue_err}", "success")
    else:
        flash("App Password saved. Sync started — watch the activity panel.", "success")
    return redirect(url_for("main.accounts"))


@bp.get("/api/recipients")
def api_recipients():
    auth = require_login_api()
    if auth is not None:
        return auth
    recipients = get_store().get_recipients(g.current_user_email)
    return jsonify(recipients)


@bp.get("/hidden")
def hidden():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    user_email = g.current_user_email
    emails = store.list_emails(user_email=user_email, only_hidden=True, exclude_hidden=False, limit=500)
    return render_template("hidden.html", emails=emails)


@bp.get("/needs-reply")
def respond_now():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    groq = get_groq_client()
    if not groq.enabled:
        flash("Add a Groq API key in Settings to use Needs Reply.", "error")
        return redirect(url_for("main.inbox"))

    store = get_store()
    user_email = g.current_user_email
    today = datetime.date.today().isoformat()
    cache = session.get("needs_reply_cache")
    groq_error = False
    recent = store.list_emails(user_email=user_email, limit=50)
    recent_count = len(recent)
    dismissed = set(session.get("needs_reply_dismissed", []))
    snoozed = session.get("needs_reply_snoozed", {})

    if cache and cache.get("date") == today and cache.get("user") == user_email:
        action_items = cache.get("items", [])
        recent_count = cache.get("total", recent_count)
    else:
        action_items, err = groq.identify_action_items(recent, today=today)
        if err:
            action_items = []
            groq_error = True
        else:
            _cache_groq_model(groq)
            session["needs_reply_cache"] = {
                "date": today,
                "user": user_email,
                "items": action_items,
                "total": recent_count,
            }

    email_map = {e["email_id"]: e for e in recent}
    results = []
    for item in action_items:
        eid = item.get("email_id", "")
        if eid in dismissed:
            continue
        snooze_until = snoozed.get(eid)
        if snooze_until and snooze_until > today:
            continue
        if eid in email_map:
            results.append({"email": email_map[eid], "reason": item.get("reason", "")})

    return render_template(
        "respond_now.html",
        results=results,
        total=recent_count,
        groq_error=groq_error,
    )


@bp.post("/needs-reply/dismiss/<email_id>")
def needs_reply_dismiss(email_id: str):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect
    dismissed = set(session.get("needs_reply_dismissed", []))
    dismissed.add(email_id)
    session["needs_reply_dismissed"] = list(dismissed)
    flash("Removed from Needs Reply.", "success")
    return redirect(url_for("main.respond_now"))


@bp.post("/needs-reply/snooze/<email_id>")
def needs_reply_snooze(email_id: str):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect
    days_raw = request.form.get("days", "3")
    days = int(days_raw) if days_raw.isdigit() and 1 <= int(days_raw) <= 30 else 3
    until = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    snoozed = dict(session.get("needs_reply_snoozed", {}))
    snoozed[email_id] = until
    session["needs_reply_snoozed"] = snoozed
    flash(f"Snoozed for {days} day(s).", "success")
    return redirect(url_for("main.respond_now"))


@bp.post("/needs-reply/draft/<email_id>")
def needs_reply_draft(email_id: str):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    email = store.get_email(email_id, user_email=g.current_user_email)
    if email is None:
        flash("Email not found.", "error")
        return redirect(url_for("main.respond_now"))

    groq = get_groq_client()
    reason = (request.form.get("reason") or "").strip()
    draft = groq.draft_reply(
        sender=email["sender"],
        subject=email["subject"],
        body=email["body"],
        reason=reason,
    )
    _cache_groq_model(groq)
    if not draft:
        flash("Could not generate a draft reply.", "error")
        return redirect(url_for("main.respond_now"))

    mailto = f"mailto:{quote(email.get('sender') or '')}?subject={quote('Re: ' + (email.get('subject') or ''))}&body={quote(draft)}"
    return render_template(
        "respond_now.html",
        results=[],
        total=0,
        groq_error=False,
        draft_reply=draft,
        draft_email=email,
        mailto_link=mailto,
    )


@bp.route("/tags", methods=["GET", "POST"])
def tags():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    user_email = g.current_user_email

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        color = (request.form.get("color") or "#888888").strip()
        use_ai = bool(request.form.get("use_ai"))
        ai_instruction = (request.form.get("ai_instruction") or "").strip()
        hide_matching = bool(request.form.get("hide_matching"))

        if not name:
            flash("Tag name is required.", "error")
        else:
            tag_id = store.save_tag(user_email, name, color, use_ai, ai_instruction, hide_matching)
            saved_rules = _save_tag_rules_from_form(store, tag_id)
            _apply_tag_after_save(
                store,
                user_email,
                tag_id,
                name,
                use_ai=use_ai,
                hide_matching=hide_matching,
                saved_rules=saved_rules,
            )
        return redirect(url_for("main.tags"))

    user_tags = store.list_tags(user_email)
    groq_available = get_groq_client().enabled
    return render_template("tags.html", tags=user_tags, groq_available=groq_available)


@bp.route("/tags/<int:tag_id>/edit", methods=["GET", "POST"])
def tags_edit(tag_id: int):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    user_email = g.current_user_email
    tag = store.get_tag(tag_id, user_email)
    if tag is None:
        flash("Tag not found.", "error")
        return redirect(url_for("main.tags"))

    if request.method == "POST":
        action = request.form.get("action", "save")

        if action == "apply_ai":
            groq = get_groq_client()
            if not groq.enabled:
                flash("Add a Groq API key in Settings to use AI tagging.", "error")
            elif not tag["use_ai"]:
                flash("Enable AI for this tag before applying.", "error")
            else:
                job_id, queue_err = _queue_job(
                    user_email,
                    "tags",
                    f"AI tagging '{tag['name']}'",
                )
                if queue_err:
                    flash(queue_err, "error")
                else:
                    flash(f"AI tagging started for '{tag['name']}' — watch the activity panel.", "success")
            return redirect(url_for("main.tags_edit", tag_id=tag_id))

        if action == "apply_manual":
            updated = store.apply_all_manual_tags(user_email)
            flash(f"Manual tag rules applied — {updated} tag change(s).", "success")
            return redirect(url_for("main.tags_edit", tag_id=tag_id))

        name = (request.form.get("name") or "").strip()
        color = (request.form.get("color") or "#888888").strip()
        use_ai = bool(request.form.get("use_ai"))
        ai_instruction = (request.form.get("ai_instruction") or "").strip()
        hide_matching = bool(request.form.get("hide_matching"))

        if not name:
            flash("Tag name is required.", "error")
        else:
            store.update_tag(tag_id, user_email, name, color, use_ai, ai_instruction, hide_matching)
            saved_rules = _save_tag_rules_from_form(store, tag_id)
            _apply_tag_after_save(
                store,
                user_email,
                tag_id,
                name,
                use_ai=use_ai,
                hide_matching=hide_matching,
                saved_rules=saved_rules,
            )
            return redirect(url_for("main.tags"))

    groq_available = get_groq_client().enabled
    return render_template("tags_edit.html", tag=tag, groq_available=groq_available)


@bp.post("/tags/<int:tag_id>/delete")
def tags_delete(tag_id: int):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect
    get_store().delete_tag(tag_id, g.current_user_email)
    flash("Tag deleted.", "success")
    return redirect(url_for("main.tags"))


@bp.post("/tags/apply")
def tags_apply():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect
    updated = get_store().apply_all_manual_tags(g.current_user_email)
    flash(f"Manual tag rules applied — {updated} tag change(s).", "success")
    return redirect(url_for("main.tags"))


@bp.post("/tags/<int:tag_id>/apply-ai")
def tags_apply_ai(tag_id: int):
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect

    store = get_store()
    user_email = g.current_user_email
    tag = store.get_tag(tag_id, user_email)
    if tag is None:
        flash("Tag not found.", "error")
        return redirect(url_for("main.tags"))

    if not tag["use_ai"]:
        flash("This tag does not use AI classification.", "error")
        return redirect(url_for("main.tags"))

    groq = get_groq_client()
    if not groq.enabled:
        flash("Add a Groq API key in Settings to use AI tagging.", "error")
        return redirect(url_for("main.tags"))

    job_id, queue_err = _queue_job(
        user_email,
        "tags",
        f"AI tagging '{tag['name']}'",
    )
    if queue_err:
        flash(queue_err, "error")
    else:
        flash(f"AI tagging started for '{tag['name']}' — watch the activity panel.", "success")
    return redirect(url_for("main.tags"))


@bp.post("/tags/apply-ai-background")
def tags_apply_ai_background():
    login_redirect = require_login()
    if login_redirect is not None:
        return login_redirect
    job_id, queue_err = _queue_job(g.current_user_email, "tags", "Apply AI tags")
    if queue_err:
        flash(queue_err, "error")
    else:
        flash("AI tagging started — watch the activity panel.", "success")
    return redirect(url_for("main.tags"))


def register_routes(app):
    app.register_blueprint(bp)
    from .services.sync_worker import start_sync_worker

    start_sync_worker(
        app,
        sync_one_account,
        get_groq_client,
        tag_apply_fn=_apply_all_tags,
        analyze_fn=analyze_pending_emails,
        digest_fn=refresh_cached_digest,
    )


def _save_tag_rules_from_form(store, tag_id: int) -> int:
    fields = request.form.getlist("rule_field")
    operators = request.form.getlist("rule_operator")
    values = request.form.getlist("rule_value")
    store.clear_tag_rules(tag_id)
    saved = 0
    for field, operator, value in zip(fields, operators, values):
        if field and operator and value.strip():
            store.save_tag_rule(tag_id, field, operator, value.strip())
            saved += 1
    return saved


def _apply_tag_after_save(
    store,
    user_email: str,
    tag_id: int,
    name: str,
    *,
    use_ai: bool,
    hide_matching: bool,
    saved_rules: int,
) -> None:
    if hide_matching and not use_ai and saved_rules == 0:
        store.seed_tag_name_rules(tag_id, name)
        flash(
            f"Hide matching is on, so emails whose subject or body contains '{name}' will be tagged and hidden.",
            "success",
        )
    applied = store.apply_all_manual_tags(user_email)
    flash(f"Tag '{name}' saved.", "success")
    if applied:
        flash(f"Applied matching rules — {applied} tag change(s).", "success")
    if use_ai:
        _, queue_err = _queue_job(user_email, "tags", f"AI tagging '{name}'")
        if queue_err:
            flash(f"{queue_err} Click Apply AI after the current job finishes.", "error")
        else:
            flash("AI tagging started — watch the activity panel.", "success")


def _apply_all_tags(store, user_email: str) -> int:
    updated = store.apply_all_manual_tags(user_email)
    updated += _apply_all_ai_tags(store, user_email)
    return updated


def _apply_all_ai_tags(store, user_email: str) -> int:
    groq = get_groq_client(user_email)
    groq.cancel_check = lambda: current_job_is_cancelled(store)
    if not groq.enabled:
        return 0
    tags = [t for t in store.list_tags(user_email) if t["use_ai"]]
    if not tags:
        return 0
    # ponytail: AI tagging only considers the 200 most recent emails.
    emails = store.list_emails(user_email=user_email, limit=200, exclude_hidden=False)
    tagged = 0
    tag_by_name = {str(t["name"]).strip().lower(): t for t in tags if str(t.get("name") or "").strip()}
    chunk_size = 8
    for start in range(0, len(emails), chunk_size):
        check_cancelled(store)
        chunk = emails[start : start + chunk_size]
        pending: list[dict] = []
        existing_map: dict[str, set[int]] = {}
        for email in chunk:
            existing_ids = {t["id"] for t in store.get_email_tags(email["email_id"])}
            existing_map[email["email_id"]] = existing_ids
            if any(tag["id"] not in existing_ids for tag in tags):
                pending.append(email)
        if not pending:
            continue
        matches = groq.classify_emails_for_tags(pending, tags)
        for email in pending:
            names = matches.get(email["email_id"]) or []
            existing_ids = existing_map[email["email_id"]]
            new_ids = set(existing_ids)
            for name in names:
                tag = tag_by_name.get(str(name).strip().lower())
                if tag is None or tag["id"] in new_ids:
                    continue
                new_ids.add(tag["id"])
                tagged += 1
                if tag["hide_matching"]:
                    store.set_email_hidden(email["email_id"], user_email, True, by_tag=True)
            if new_ids != existing_ids:
                store.set_email_tags(email["email_id"], list(new_ids))
    _cache_groq_model(groq)
    return tagged
