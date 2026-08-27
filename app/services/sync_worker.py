"""Background IMAP sync and AI analysis queue so HTTP handlers return immediately."""
from __future__ import annotations

import threading
from contextvars import ContextVar
from queue import Empty, Queue
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from flask import Flask

_sync_queue: Queue[tuple[str, str, list[int] | None, str]] = Queue()
_worker_started = False
_worker_lock = threading.Lock()
_current_job_id: ContextVar[str] = ContextVar("email_tools_job_id", default="")

ProgressFn = Callable[..., None]
SyncFn = Callable[..., Any]
AnalyzeFn = Callable[..., int]
DigestFn = Callable[..., None]
TagFn = Callable[..., int]


class JobCancelled(Exception):
    """User cancelled the in-flight background job."""


def enqueue_job(
    job_id: str,
    job_type: str,
    user_email: str,
    account_ids: list[int] | None = None,
) -> None:
    """Queue a tracked job for the background worker."""
    _sync_queue.put((job_id, job_type, account_ids, user_email))


def enqueue_sync(user_email: str, account_ids: list[int] | None = None, job_type: str = "sync") -> None:
    """Legacy helper — prefer enqueue_job with a store-created job id."""
    _sync_queue.put(("", job_type, account_ids, user_email))


def sync_queue_size() -> int:
    return _sync_queue.qsize()


def current_job_is_cancelled(store: Any) -> bool:
    job_id = _current_job_id.get()
    return bool(job_id) and store.job_was_cancelled(job_id)


def check_cancelled(store: Any) -> None:
    """Raise JobCancelled if the current worker job was cancelled."""
    if current_job_is_cancelled(store):
        raise JobCancelled()


def start_sync_worker(
    app: Flask,
    sync_fn: SyncFn,
    get_groq_client: Callable[[str], Any],
    tag_apply_fn: TagFn | None = None,
    analyze_fn: AnalyzeFn | None = None,
    digest_fn: DigestFn | None = None,
) -> None:
    """Start the daemon worker thread once per process."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True

    def _worker() -> None:
        while True:
            try:
                job_id, job_type, account_ids, user_email = _sync_queue.get(timeout=1)
            except Empty:
                continue
            with app.app_context():
                store = app.extensions["email_store"]
                if not job_id:
                    job_id = store.create_job(user_email, job_type, job_type.title())
                _run_job(
                    store,
                    job_id,
                    job_type,
                    account_ids,
                    user_email,
                    sync_fn,
                    get_groq_client,
                    tag_apply_fn,
                    analyze_fn,
                    digest_fn,
                )
            _sync_queue.task_done()

    thread = threading.Thread(target=_worker, name="email-sync-worker", daemon=True)
    thread.start()


def _run_job(
    store: Any,
    job_id: str,
    job_type: str,
    account_ids: list[int] | None,
    user_email: str,
    sync_fn: SyncFn,
    get_groq_client: Callable[[str], Any],
    tag_apply_fn: TagFn | None,
    analyze_fn: AnalyzeFn | None,
    digest_fn: DigestFn | None,
) -> None:
    token = _current_job_id.set(job_id)
    try:
        _run_job_inner(
            store,
            job_id,
            job_type,
            account_ids,
            user_email,
            sync_fn,
            get_groq_client,
            tag_apply_fn,
            analyze_fn,
            digest_fn,
        )
    finally:
        _current_job_id.reset(token)


def _run_job_inner(
    store: Any,
    job_id: str,
    job_type: str,
    account_ids: list[int] | None,
    user_email: str,
    sync_fn: SyncFn,
    get_groq_client: Callable[[str], Any],
    tag_apply_fn: TagFn | None,
    analyze_fn: AnalyzeFn | None,
    digest_fn: DigestFn | None,
) -> None:
    if store.job_was_cancelled(job_id):
        store.append_job_log(job_id, "Skipped — already cancelled.")
        return

    store.update_job(job_id, status="running", message="Starting…")
    store.append_job_log(job_id, "Worker picked up this job.")

    def report(message: str, current: int | None = None, total: int | None = None) -> None:
        check_cancelled(store)
        store.append_job_log(job_id, message)
        fields: dict[str, object] = {}
        if current is not None:
            fields["current_step"] = current
        if total is not None:
            fields["total_steps"] = total
        if fields:
            store.update_job(job_id, **fields)

    errors: list[str] = []
    try:
        groq = get_groq_client(user_email)
        groq.cancel_check = lambda: store.job_was_cancelled(job_id)

        if job_type == "tags":
            if tag_apply_fn:
                report("Applying tags…")
                tagged = tag_apply_fn(store, user_email)
                report(f"Tagging finished — {tagged} assignment(s).")
            else:
                report("No tag-apply handler configured.")
            store.update_job(job_id, status="done", current_step=1, total_steps=1, message="Tagging finished.")
            return

        if job_type in ("sync", "backfill"):
            accounts = store.list_imap_accounts(user_email)
            if account_ids:
                accounts = [a for a in accounts if a["id"] in account_ids]
            if not accounts:
                report("No matching IMAP accounts to sync.")
            total_imported = 0
            for index, account in enumerate(accounts, start=1):
                check_cancelled(store)
                report(
                    f"Syncing {account['account_email']} ({index}/{len(accounts)})…",
                    current=index - 1,
                    total=max(len(accounts), 1),
                )
                try:
                    imported, err = sync_fn(
                        store,
                        account,
                        user_email,
                        groq,
                        backfill_only=(job_type == "backfill"),
                        on_progress=report,
                    )
                    total_imported += imported
                    if err:
                        errors.append(err)
                        report(err)
                    else:
                        report(f"{account['account_email']}: saved {imported} message(s).")
                except JobCancelled:
                    raise
                except Exception as exc:
                    msg = f"{account.get('account_email', 'account')}: {exc}"
                    errors.append(msg)
                    report(msg)
            report(f"Mail fetch finished — {total_imported} message(s) saved.", current=len(accounts), total=max(len(accounts), 1))

            if groq.enabled and analyze_fn:
                report("Starting automatic AI analysis…")
                analyzed = analyze_fn(store, user_email, groq, report)
                report(f"AI analysis finished — {analyzed} email(s) summarized.")
            elif not groq.enabled:
                report("No Groq key — mail is cached with quick local summaries. Add a key in Settings for a real AI brief.")

            if tag_apply_fn:
                report("Applying tags…")
                tagged = tag_apply_fn(store, user_email)
                report(f"Tagging finished — {tagged} assignment(s).")

            if digest_fn:
                report("Refreshing inbox brief…")
                digest_fn(store, user_email, groq if groq.enabled else None)
                report("Inbox brief updated.")

        elif job_type == "reanalyze":
            if not groq.enabled:
                store.update_job(
                    job_id,
                    status="error",
                    error="Add a Groq API key in Settings to analyze with AI.",
                    message="Groq is not configured.",
                )
                report("Stopped — Groq API key missing.")
                return
            if analyze_fn:
                analyzed = analyze_fn(store, user_email, groq, report)
                report(f"AI analysis finished — {analyzed} email(s) summarized.")
            if tag_apply_fn:
                report("Applying tags…")
                tagged = tag_apply_fn(store, user_email)
                report(f"Tagging finished — {tagged} assignment(s).")
            if digest_fn:
                report("Refreshing inbox brief…")
                digest_fn(store, user_email, groq)
                report("Inbox brief updated.")
        else:
            report(f"Unknown job type: {job_type}")

        if errors:
            store.update_job(
                job_id,
                status="error",
                error=" · ".join(errors[:3]),
                message=errors[0],
            )
        else:
            store.update_job(job_id, status="done", message="Finished.")
            store.append_job_log(job_id, "Finished.")
    except JobCancelled:
        store.append_job_log(job_id, "Stopped after cancel.")
    except Exception as exc:
        store.append_job_log(job_id, f"Failed: {exc}")
        store.update_job(job_id, status="error", error=str(exc), message=str(exc))
