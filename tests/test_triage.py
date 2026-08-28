from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from app.services.store import EmailStore
from app.services.summary import build_email_record
from app.services.triage import (
    build_fyi_digest,
    build_today_view,
    infer_intent_heuristic,
    rebuild_thread_states,
)


def _sample_message(**overrides) -> dict:
    base = {
        "email_id": "msg-1",
        "message_id": "<a@b>",
        "subject": "Can you review this?",
        "sender": "boss@company.com",
        "recipient": "me@example.com",
        "cc": "",
        "body": "Please reply by Friday with your thoughts.",
        "received_at": "2026-08-27T10:00:00+00:00",
        "in_reply_to": "",
        "is_mailing_list": 0,
    }
    base.update(overrides)
    return base


def test_infer_intent_heuristic_i_owe() -> None:
    intent, reason, _ = infer_intent_heuristic(
        {"subject": "Question?", "body": "Please reply", "bullet_summary": [], "is_mailing_list": 0},
        from_me=False,
        last_from_me_at=None,
        last_inbound_at="2026-08-27T10:00:00+00:00",
        vip=False,
        always_hide=False,
    )
    assert intent == "i_owe"
    assert reason


def test_today_view_do_now() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "triage.db")
        store.initialize()
        user = "me@example.com"
        record = build_email_record(
            _sample_message(),
            source_name="me@example.com",
            user_email=user,
            source_account="me@example.com",
        )
        record["intent"] = "i_owe"
        record["intent_reason"] = "Needs reply"
        record["urgency"] = 90
        store.bulk_upsert([record])
        rebuild_thread_states(store, user)
        view = build_today_view(store, user)
        assert len(view["do_now"]) == 1
        assert view["do_now"][0]["subject"] == "Can you review this?"


def test_today_route_renders_do_now() -> None:
    from app import create_app
    from werkzeug.security import generate_password_hash

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    store: EmailStore = app.extensions["email_store"]
    user = f"today-user-{uuid.uuid4().hex[:8]}@example.com"
    store.set_app_password(user, generate_password_hash("secret12", method="pbkdf2:sha256"))
    record = build_email_record(
        _sample_message(),
        source_name=user,
        user_email=user,
        source_account=user,
    )
    record["intent"] = "i_owe"
    record["intent_reason"] = "Needs reply"
    record["urgency"] = 90
    store.bulk_upsert([record])
    rebuild_thread_states(store, user)

    with app.test_client() as client:
        client.post("/login", data={"email": user, "app_password": "secret12"})
        response = client.get("/today")
        assert response.status_code == 200
        assert b"Do now" in response.data
        assert b"Can you review this?" in response.data
        assert b"FYI digest" in response.data

        redirect = client.get("/needs-reply", follow_redirects=False)
        assert redirect.status_code == 302
        assert "/today" in redirect.headers["Location"]


def test_today_route_with_ai_reads_fyi_digest_dict() -> None:
    from unittest.mock import MagicMock, patch

    from app import create_app
    from werkzeug.security import generate_password_hash

    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    store: EmailStore = app.extensions["email_store"]
    user = f"today-fyi-{uuid.uuid4().hex[:8]}@example.com"
    store.set_app_password(user, generate_password_hash("secret12", method="pbkdf2:sha256"))
    rec = build_email_record(
        _sample_message(
            email_id="fyi-1",
            message_id="<fyi@b>",
            subject="FYI note",
            body="Just FYI.",
        ),
        source_name=user,
        user_email=user,
        source_account=user,
    )
    rec["intent"] = "fyi"
    rec["ai_analyzed"] = 1
    store.bulk_upsert([rec])
    rebuild_thread_states(store, user)

    fake_ai = MagicMock()
    fake_ai.enabled = True
    fake_ai.build_inbox_digest.return_value = {"headline": "Today skim", "bullets": ["Note"]}

    with app.test_client() as client:
        client.post("/login", data={"email": user, "app_password": "secret12"})
        with patch("app.routes.get_ai_client", return_value=fake_ai):
            with patch("app.routes._queue_job"):
                response = client.get("/today")
        assert response.status_code == 200
        assert b"FYI digest" in response.data
        assert b"Today skim" in response.data


def test_fyi_digest_curated_cap() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "fyi.db")
        store.initialize()
        user = "me@example.com"
        records = []
        for i in range(10):
            msg = _sample_message(
                email_id=f"msg-{i}",
                message_id=f"<m{i}@b>",
                subject=f"FYI update {i}",
                body="Informational only.",
                received_at=f"2026-08-{20 + i}T10:00:00+00:00",
            )
            rec = build_email_record(
                msg,
                source_name=user,
                user_email=user,
                source_account=user,
            )
            rec["intent"] = "fyi"
            rec["urgency"] = 20 + i
            rec["is_read"] = 1 if i > 2 else 0
            records.append(rec)
        store.bulk_upsert(records)
        rebuild_thread_states(store, user)
        view = build_today_view(store, user)
        digest = view["fyi_digest"]
        assert len(digest["thread_ids"]) <= 6
        assert digest["headline"].startswith(str(len(digest["thread_ids"])))
        assert "64" not in digest["headline"]
        assert digest["bullets"]
        assert all(isinstance(b, dict) and b.get("email_id") for b in digest["bullets"])


def test_load_fyi_brief_reads_digest_dict() -> None:
    from app.routes import _load_fyi_brief

    class _FakeAI:
        def __init__(self) -> None:
            self.enabled = True
            self.seen: list[list] = []

        def build_inbox_digest(self, emails):
            self.seen.append(emails)
            return {"headline": "Skim these", "bullets": ["One update"]}

    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "brief.db")
        store.initialize()
        user = "me@example.com"
        rec = build_email_record(
            _sample_message(
                email_id="msg-fyi",
                message_id="<fyi@b>",
                subject="FYI update",
                body="Informational only.",
            ),
            source_name=user,
            user_email=user,
            source_account=user,
        )
        rec["intent"] = "fyi"
        rec["urgency"] = 20
        rec["is_read"] = 0
        store.bulk_upsert([rec])
        rebuild_thread_states(store, user)
        view = build_today_view(store, user)
        ai = _FakeAI()
        brief = _load_fyi_brief(store, user, view["fyi_digest"], ai)
        assert brief is not None
        assert brief["headline"] == "Skim these"
        assert ai.seen and ai.seen[0]


def test_add_todo_survives_rebuild() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "todo.db")
        store.initialize()
        user = "me@example.com"
        record = build_email_record(
            _sample_message(subject="Newsletter skim"),
            source_name=user,
            user_email=user,
            source_account=user,
        )
        record["intent"] = "fyi"
        record["urgency"] = 30
        store.bulk_upsert([record])
        rebuild_thread_states(store, user)
        thread_id = record["thread_id"]
        store.record_thread_user_action(user, thread_id, "add_todo")
        rebuild_thread_states(store, user)
        view = build_today_view(store, user)
        assert any(r["thread_id"] == thread_id and r.get("on_todo") for r in view["do_now"])
        state = store.get_thread_state(user, thread_id)
        assert state and state.get("intent") == "i_owe"
        assert state.get("user_moved") == 1


def test_remove_todo_blocks_vip_repromote() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "vip.db")
        store.initialize()
        user = "me@example.com"
        store.save_sender_rule(user, "boss@company.com", "vip")
        record = build_email_record(
            _sample_message(sender="boss@company.com"),
            source_name=user,
            user_email=user,
            source_account=user,
        )
        record["intent"] = "fyi"
        store.bulk_upsert([record])
        rebuild_thread_states(store, user)
        thread_id = record["thread_id"]
        store.record_thread_user_action(user, thread_id, "remove_todo")
        rebuild_thread_states(store, user)
        state = store.get_thread_state(user, thread_id)
        assert state and state.get("intent") == "fyi"
        assert state.get("on_todo") == 0


def test_search_sort_urgency() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "search.db")
        store.initialize()
        user = "me@example.com"
        low = build_email_record(
            _sample_message(email_id="low", message_id="<l>", subject="Low", received_at="2026-08-20T10:00:00+00:00"),
            source_name=user,
            user_email=user,
            source_account=user,
        )
        high = build_email_record(
            _sample_message(email_id="high", message_id="<h>", subject="High", received_at="2026-08-21T10:00:00+00:00"),
            source_name=user,
            user_email=user,
            source_account=user,
        )
        low["urgency"] = 10
        high["urgency"] = 90
        store.bulk_upsert([low, high])
        results = store.list_emails(user_email=user, sort="urgency", limit=10)
        assert len(results) == 2
        assert results[0]["urgency"] >= results[1]["urgency"]
        assert results[0]["subject"] == "High"
