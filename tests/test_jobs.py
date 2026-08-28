from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from app import create_app
from app.services.groq_client import GroqClient
from app.services.store import EmailStore, job_percent_from_phases
from app.services.sync_worker import JobFailed, _run_job
from app.services.summary import build_email_record


def test_store_jobs_and_kv_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "t.db")
        store.initialize()
        job_id = store.create_job("me@example.com", "sync", "Sync inbox")
        store.append_job_log(job_id, "Fetching INBOX…")
        store.update_job(job_id, status="running", current_step=1, total_steps=4)
        job = store.get_job(job_id, "me@example.com")
        assert job is not None
        assert job["status"] == "running"
        assert job["log"][-1] == "Fetching INBOX…"
        assert job["percent"] == 25
        assert store.get_active_job("me@example.com")["id"] == job_id

        store.set_kv("me@example.com", "inbox_digest", json.dumps({"headline": "Hi", "bullets": ["a"]}))
        assert json.loads(store.get_kv("me@example.com", "inbox_digest"))["headline"] == "Hi"


def test_job_phase_progress_and_percent() -> None:
    phases = {
        "fetch": {"current": 50, "total": 100},
        "summarize": {"current": 0, "total": 10},
    }
    assert job_percent_from_phases(phases) == 25

    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "t.db")
        store.initialize()
        job_id = store.create_job("me@example.com", "sync", "Sync inbox")
        store.update_job_phase(job_id, "fetch", 40, 200, message="Downloading…")
        job = store.get_job(job_id, "me@example.com")
        assert job is not None
        assert job["phases"]["fetch"]["current"] == 40
        assert job["percent"] == 10


def test_list_unanalyzed_emails() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "t.db")
        store.initialize()
        message = {
            "email_id": "raw-1",
            "message_id": "<a@b>",
            "subject": "Hello",
            "sender": "a@b.com",
            "recipient": "me@example.com",
            "cc": "",
            "received_at": "2026-01-01T12:00:00",
            "body": "Please review the report.",
            "is_mailing_list": 0,
        }
        record = build_email_record(message, "me@example.com", "me@example.com", source_account="me@example.com")
        store.bulk_upsert([record])
        pending = store.list_unanalyzed_emails("me@example.com", 10)
        assert len(pending) == 1
        assert pending[0]["subject"] == "Hello"


def test_run_job_records_decrypt_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "t.db")
        store.initialize()
        store.save_imap_account(
            "me@example.com",
            "acct@example.com",
            "imap.example.com",
            993,
            "ciphertext",
        )
        job_id = store.create_job("me@example.com", "sync", "Sync acct")

        def sync_fn(*_args, **_kwargs):
            return 0, "acct@example.com: could not decrypt the saved App Password."

        groq = MagicMock()
        groq.enabled = False
        _run_job(
            store,
            job_id,
            "sync",
            None,
            "me@example.com",
            sync_fn,
            lambda _email: groq,
            None,
            None,
            None,
        )
        job = store.get_job(job_id, "me@example.com")
        assert job is not None
        assert job["status"] == "error"
        assert "decrypt" in job["error"]
        assert any("decrypt" in line for line in job["log"])


def test_run_job_stops_on_analyze_failure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "t.db")
        store.initialize()
        job_id = store.create_job("me@example.com", "reanalyze", "Analyze")

        def analyze_fn(*_args, **_kwargs):
            raise JobFailed(
                "400 INVALID_ARGUMENT. Request contains an invalid argument."
            )

        groq = MagicMock()
        groq.enabled = True
        groq.last_error = ""
        _run_job(
            store,
            job_id,
            "reanalyze",
            None,
            "me@example.com",
            lambda *_a, **_k: (0, None),
            lambda _email: groq,
            None,
            analyze_fn,
            None,
        )
        job = store.get_job(job_id, "me@example.com")
        assert job is not None
        assert job["status"] == "error"
        assert "INVALID_ARGUMENT" in job["error"]
        assert any("Stopped:" in line for line in job["log"])


def test_api_jobs_requires_auth() -> None:
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        response = client.get("/api/jobs")
        assert response.status_code == 401


def test_analyze_requires_login() -> None:
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.test_client() as client:
        response = client.post("/analyze")
        assert response.status_code == 302
        assert "/login" in response.headers.get("Location", "")


def test_cancel_active_job_unblocks_queue() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "t.db")
        store.initialize()
        job_id = store.create_job("me@example.com", "sync", "Sync inbox")
        store.update_job(job_id, status="running", message="Stuck…")
        assert store.get_active_job("me@example.com") is not None
        cancelled = store.cancel_active_jobs("me@example.com")
        assert cancelled == [job_id]
        assert store.get_active_job("me@example.com") is None
        job = store.get_job(job_id, "me@example.com")
        assert job is not None
        assert job["status"] == "cancelled"
        store.update_job(job_id, status="done", message="should not stick")
        assert store.get_job(job_id, "me@example.com")["status"] == "cancelled"


def test_run_job_skips_cancelled() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "t.db")
        store.initialize()
        job_id = store.create_job("me@example.com", "sync", "Sync inbox")
        store.cancel_active_jobs("me@example.com")
        sync_fn = MagicMock()
        groq = MagicMock()
        groq.enabled = False
        _run_job(
            store,
            job_id,
            "sync",
            None,
            "me@example.com",
            sync_fn,
            lambda _email: groq,
            None,
            None,
            None,
        )
        sync_fn.assert_not_called()
        assert store.get_job(job_id, "me@example.com")["status"] == "cancelled"


def test_jobs_cancel_requires_auth() -> None:
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.test_client() as client:
        response = client.post("/jobs/cancel", headers={"Accept": "application/json"})
        assert response.status_code == 401


@patch("app.services.groq_client.requests.post")
def test_summarize_emails_batch_parses_items(mock_post: MagicMock) -> None:
    mock_post.return_value = MagicMock(
        status_code=200,
        ok=True,
        raise_for_status=lambda: None,
        json=lambda: {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "items": [
                                    {"id": "abc", "bullets": ["Pay the invoice", "Due Friday"]},
                                ]
                            }
                        )
                    }
                }
            ]
        },
    )
    client = GroqClient(api_key="gsk_test", default_model="openai/gpt-oss-20b")
    client._cached_best_model = "openai/gpt-oss-20b"
    result = client.summarize_emails_batch(
        [{"email_id": "abc", "sender": "a@b", "subject": "Invoice", "body": "Please pay"}]
    )
    assert result["abc"][0] == "Pay the invoice"


def test_retired_default_model_is_remapped() -> None:
    client = GroqClient(api_key="gsk_test", default_model="llama-3.3-70b-versatile")
    assert client.default_model == "openai/gpt-oss-20b"


@patch("app.services.groq_client.requests.post")
def test_complete_falls_back_from_decommissioned_model(mock_post: MagicMock) -> None:
    dead = MagicMock(status_code=400, ok=False, text="model decommissioned")
    dead.json.return_value = {"error": {"message": "The model `llama-3.3-70b-versatile` has been decommissioned"}}
    live = MagicMock(status_code=200, ok=True)
    live.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"bullets": ["Action: reply today"]})}}]
    }
    mock_post.side_effect = [dead, live]
    client = GroqClient(api_key="gsk_test", default_model="openai/gpt-oss-120b")
    result = client.summarize_email("a@b.com", "Hello", "Please reply")
    assert result == {"bullets": ["Action: reply today"], "line": "", "compact": ""}
    assert mock_post.call_count == 2
    assert client._cached_best_model in (
        "openai/gpt-oss-20b",
        "qwen/qwen3.8-27b",
        "qwen/qwen3.6-27b",
    )


@patch("app.services.groq_client.time.sleep")
@patch("app.services.groq_client.requests.post")
def test_complete_falls_back_from_rate_limit(mock_post: MagicMock, mock_sleep: MagicMock) -> None:
    limited = MagicMock(status_code=429, ok=False, text="rate limit", headers={"Retry-After": "22.4925"})
    limited.json.return_value = {
        "error": {
            "message": (
                "Rate limit reached for model `openai/gpt-oss-120b` "
                "on tokens per minute (TPM): Limit 8000, Used 5650, Requested 5349."
            )
        }
    }
    live = MagicMock(status_code=200, ok=True)
    live.json.return_value = {
        "choices": [{"message": {"content": json.dumps({"bullets": ["Action: reply today"]})}}]
    }
    mock_post.side_effect = [limited, live]
    client = GroqClient(api_key="gsk_test", default_model="openai/gpt-oss-120b")
    client._cached_best_model = "openai/gpt-oss-120b"
    result = client.summarize_email("a@b.com", "Hello", "Please reply")
    assert result == {"bullets": ["Action: reply today"], "line": "", "compact": ""}
    assert mock_sleep.call_count == 0
    assert mock_post.call_count == 2
    assert mock_post.call_args_list[0].kwargs["json"]["model"] == "openai/gpt-oss-120b"
    assert mock_post.call_args_list[1].kwargs["json"]["model"] == "openai/gpt-oss-20b"
    assert client._cached_best_model == "openai/gpt-oss-20b"
    assert "openai/gpt-oss-120b" in client._rate_limited_models


def test_hide_matching_tag_applies_name_rules() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "t.db")
        store.initialize()
        message = {
            "email_id": "raw-adm",
            "message_id": "<adm@b>",
            "subject": "College admissions decision",
            "sender": "admit@college.edu",
            "recipient": "me@example.com",
            "cc": "",
            "received_at": "2026-01-01T12:00:00",
            "body": "Your college admissions file is complete.",
            "is_mailing_list": 0,
        }
        record = build_email_record(message, "me@example.com", "me@example.com", source_account="me@example.com")
        store.bulk_upsert([record])
        tag_id = store.save_tag("me@example.com", "college admissions", "#2d8f85", False, "", True)
        updated = store.apply_all_manual_tags("me@example.com")
        assert updated >= 1
        tag = store.get_tag(tag_id, "me@example.com")
        assert tag is not None
        assert len(tag["rules"]) == 2
        email = store.get_email(record["email_id"], "me@example.com")
        assert email is not None
        assert email["is_hidden"] == 1
        names = [t["name"] for t in store.get_email_tags(record["email_id"])]
        assert "college admissions" in names


def test_default_school_tag_matches_admissions_sender() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "t.db")
        store.initialize()
        for sender in (
            "Rose-Hulman Admissions <admissions@rose-hulman.edu>",
            "Clarkson University <admissions@clarkson.edu>",
        ):
            message = {
                "email_id": f"raw-{hash(sender)}",
                "message_id": f"<{sender}>",
                "subject": "Explore our programs",
                "sender": sender,
                "recipient": "me@example.com",
                "cc": "",
                "received_at": "2026-01-01T12:00:00",
                "body": "Apply now to begin your journey.",
                "is_mailing_list": 1,
            }
            record = build_email_record(
                message, "me@example.com", "me@example.com", source_account="me@example.com"
            )
            store.bulk_upsert([record])
        store.ensure_default_tags("me@example.com")
        emails = store.list_emails(user_email="me@example.com")
        assert len(emails) == 2
        for email in emails:
            names = [t["name"] for t in store.get_email_tags(email["email_id"])]
            assert "School" in names


def test_tag_scan_skips_repeat_groq() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "t.db")
        store.initialize()
        store.save_tag("me@example.com", "Work", "#2d8f85", True, "work related", False)
        message = {
            "email_id": "raw-work",
            "message_id": "<w@b>",
            "subject": "Project update",
            "sender": "boss@company.com",
            "recipient": "me@example.com",
            "cc": "",
            "received_at": "2026-01-01T12:00:00",
            "body": "Please review the roadmap.",
            "is_mailing_list": 0,
        }
        record = build_email_record(message, "me@example.com", "me@example.com", source_account="me@example.com")
        store.bulk_upsert([record])
        store.save_tag_scan(record["email_id"], store.list_tags("me@example.com")[0]["id"], "no")
        scans = store.get_tag_scans_for_email(record["email_id"])
        assert scans


def test_groq_unreachable_detection() -> None:
    from app.services.groq_client import is_groq_unreachable

    assert is_groq_unreachable("HTTPSConnectionPool: Failed to resolve 'api.groq.com'")
    assert not is_groq_unreachable("HTTP 401: invalid api key")


def test_build_digest_bullet_objects() -> None:
    from app.services.summary import build_digest

    emails = [
        {
            "email_id": "e1",
            "subject": "Hello",
            "sender": "a@b.com",
            "bullet_summary": ["Needs reply by Friday"],
            "preview": "preview",
            "priority_score": 50,
            "category": "Work",
        }
    ]
    digest = build_digest(emails, has_imap_accounts=False)
    linked = [b for b in digest["bullets"] if b.get("email_id") == "e1"]
    assert linked
    assert "Friday" in linked[0]["text"]
