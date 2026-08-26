"""Background IMAP sync and AI tag-apply queue so HTTP handlers return immediately."""
from __future__ import annotations

import threading
from queue import Empty, Queue
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from flask import Flask

_sync_queue: Queue[tuple[str, list[int] | None, str]] = Queue()
_worker_started = False
_worker_lock = threading.Lock()


def enqueue_sync(user_email: str, account_ids: list[int] | None = None, job_type: str = "sync") -> None:
    """Queue a sync, tag-apply, or reanalyze job for the background worker."""
    _sync_queue.put((job_type, account_ids, user_email))


def sync_queue_size() -> int:
    return _sync_queue.qsize()


def start_sync_worker(
    app: Flask,
    sync_fn: Callable[..., tuple[int, str | None]],
    get_groq_client: Callable[[str], Any],
    tag_apply_fn: Callable[..., int] | None = None,
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
                job_type, account_ids, user_email = _sync_queue.get(timeout=1)
            except Empty:
                continue
            with app.app_context():
                store = app.extensions["email_store"]
                if job_type == "tags":
                    if tag_apply_fn:
                        tag_apply_fn(store, user_email)
                    _sync_queue.task_done()
                    continue

                if job_type == "reanalyze":
                    groq = get_groq_client(user_email)
                    if groq.enabled:
                        for email_id in store.list_unanalyzed_email_ids(user_email, 100):
                            email = store.get_email(email_id, user_email=user_email)
                            if not email:
                                continue
                            bullets = groq.summarize_email(
                                sender=email["sender"],
                                subject=email["subject"],
                                body=email["body"],
                            )
                            if bullets:
                                store.update_email_summary(email_id, user_email, bullets)
                    _sync_queue.task_done()
                    continue

                groq = get_groq_client(user_email)
                accounts = store.list_imap_accounts(user_email)
                if account_ids:
                    accounts = [a for a in accounts if a["id"] in account_ids]
                for account in accounts:
                    try:
                        sync_fn(store, account, user_email, groq)
                    except Exception:
                        pass
                _sync_queue.task_done()

    thread = threading.Thread(target=_worker, name="email-sync-worker", daemon=True)
    thread.start()
