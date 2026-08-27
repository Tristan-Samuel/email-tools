from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from app.services.store import EmailStore
from app.services.summary import build_email_record
from app.services.triage import build_today_view, infer_intent_heuristic, rebuild_thread_states


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
