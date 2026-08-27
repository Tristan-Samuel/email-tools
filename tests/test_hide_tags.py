from __future__ import annotations

import tempfile
from pathlib import Path

from app.services.store import EmailStore
from app.services.summary import build_email_record


def test_school_tag_prevents_marketing_hide() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "t.db")
        store.initialize()
        message = {
            "email_id": "school-grade",
            "message_id": "<g@b>",
            "subject": "Independent study grade",
            "sender": "Mrs. Velez <vvelez-wyche@ghcds.org>",
            "recipient": "parent@example.com",
            "cc": "",
            "received_at": "2026-01-01T12:00:00",
            "body": "Many universities offer college credit for Cambridge exams.",
            "body_html": "",
            "is_mailing_list": 0,
        }
        record = build_email_record(message, "me@example.com", "me@example.com", source_account="me@example.com")
        store.bulk_upsert([record])
        store.ensure_default_tags("me@example.com")
        email = store.get_email(record["email_id"], "me@example.com")
        assert email is not None
        assert email["is_hidden"] == 0
        tag_names = [t["name"] for t in store.get_email_tags(record["email_id"])]
        assert "School" in tag_names or "Marketing" in tag_names


def test_marketing_offer_rule_not_seeded() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "t.db")
        store.initialize()
        store.ensure_default_tags("me@example.com")
        marketing = next(t for t in store.list_tags("me@example.com") if t["name"] == "Marketing")
        values = {r["value"].lower() for r in marketing["rules"]}
        assert "offer" not in values


def test_ai_confirm_tag_column() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "t.db")
        store.initialize()
        tag_id = store.save_tag("me@example.com", "Promo", "#c66150", False, "", True, True)
        tag = store.get_tag(tag_id, "me@example.com")
        assert tag is not None
        assert tag["ai_confirm"] == 1
