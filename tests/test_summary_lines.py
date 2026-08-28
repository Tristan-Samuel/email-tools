from __future__ import annotations

import tempfile
from pathlib import Path

from app.services.groq_client import parse_analyze_entry
from app.services.store import EmailStore
from app.services.summary import (
    COMPACT_SUMMARY_MAX,
    build_email_record,
    derive_compact_summary,
    derive_line_summary,
    email_row_summaries,
    fill_summary_fields,
)


def test_derive_line_is_not_just_first_bullet() -> None:
    line = derive_line_summary(
        bullets=["Please approve the invoice by Friday."],
        preview="Accounting needs the Q3 invoice signed before Friday close.",
        sender="billing@acme.com",
        subject="Vendor payment",
    )
    assert line.startswith("Vendor payment:")
    assert "Accounting needs" in line


def test_compact_is_shorter_than_line() -> None:
    line = "Acme billing needs the Q3 invoice signed before Friday close of business."
    compact = derive_compact_summary(line)
    assert len(compact) <= COMPACT_SUMMARY_MAX
    assert compact != line


def test_fill_summary_fields_prefers_ai_line() -> None:
    line, compact, bullets = fill_summary_fields(
        line="Acme wants the invoice approved today.",
        compact="Approve Acme invoice",
        bullets=["Due Friday", "Amount is $400"],
        preview="Please pay",
        sender="a@b.com",
        subject="Invoice",
    )
    assert line == "Acme wants the invoice approved today."
    assert compact == "Approve Acme invoice"
    assert bullets == ["Due Friday", "Amount is $400"]


def test_parse_analyze_entry_reads_line_and_compact() -> None:
    parsed = parse_analyze_entry(
        {
            "id": "abc",
            "line": "Reply to Sam about the lease.",
            "compact": "Reply to Sam",
            "bullets": ["Lease ends in June"],
            "intent": "i_owe",
        }
    )
    assert parsed is not None
    assert parsed["line"] == "Reply to Sam about the lease."
    assert parsed["compact"] == "Reply to Sam"
    assert parsed["intent"] == "i_owe"


def test_row_summaries_fall_back_for_legacy_mail() -> None:
    line, compact = email_row_summaries(
        {
            "bullet_summary": ["First key point only"],
            "preview": "Body preview",
        }
    )
    assert line == "First key point only"
    assert compact


def test_empty_line_summary_counts_as_pending() -> None:
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
        record = build_email_record(
            message, "me@example.com", "me@example.com", source_account="me@example.com"
        )
        store.bulk_upsert([record])
        store.update_email_analysis(
            record["email_id"],
            "me@example.com",
            bullet_summary=["Please review the report."],
            line_summary="",
            compact_summary="",
            ai_analyzed=True,
        )
        analyzed, pending = store.count_ai_stats("me@example.com")
        assert analyzed == 0
        assert pending == 1
        assert len(store.list_unanalyzed_emails("me@example.com", 10)) == 1
        cleared = store.clear_ai_analyzed("me@example.com")
        assert cleared == 1
        assert store.reset_account_sync_cursors(99, "me@example.com") is False
