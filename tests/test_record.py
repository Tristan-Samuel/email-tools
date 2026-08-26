from __future__ import annotations

from app.services.summary import build_email_record


def test_build_email_record_includes_flags_and_scoped_id() -> None:
    message = {
        "email_id": "abc123",
        "message_id": "<test@example.com>",
        "subject": "Hello",
        "sender": "sender@example.com",
        "recipient": "me@example.com",
        "cc": "",
        "received_at": "2026-01-01T12:00:00",
        "body": "Body text",
        "is_mailing_list": 1,
    }
    record = build_email_record(
        message,
        source_name="me@example.com",
        user_email="me@example.com",
        source_account="other@example.com",
    )
    assert record["is_mailing_list"] == 1
    assert record["ai_analyzed"] == 0
    assert record["email_id"] != message["email_id"]
    assert record["thread_id"]

    record_same_account = build_email_record(
        message,
        source_name="me@example.com",
        user_email="me@example.com",
        source_account="me@example.com",
    )
    assert record["email_id"] != record_same_account["email_id"]
