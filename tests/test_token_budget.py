"""Tests for Gemini token-budget email packing."""
from __future__ import annotations

from app.services.token_budget import (
    BudgetLimits,
    TokenCounter,
    format_analyze_email_block,
    pack_email_batch,
)


class _CharCounter(TokenCounter):
    """Force char/4 fallback for deterministic tests."""

    def __init__(self) -> None:
        self.model_name = "gemini-2.5-flash-lite"
        self._api_client = None
        self._local = None

    def count(self, text: str) -> int:
        return max(1, len(text) // 4)


def test_pack_email_batch_greedy_fill() -> None:
    counter = _CharCounter()
    limits = BudgetLimits(tpm=800, tpd=1_000_000, body_chars=200, max_emails_per_batch=10)
    emails = [
        {
            "email_id": f"id-{i}",
            "sender": f"user{i}@example.com",
            "subject": f"Subject {i}",
            "body": f"Body text number {i} " * 5,
            "from_me": False,
        }
        for i in range(20)
    ]
    packed, blocks = pack_email_batch(emails, counter, limits, remaining_tpd=500_000)
    assert packed
    assert len(packed) == len(blocks)
    assert len(packed) > 1
    assert len(packed) < len(emails)


def test_pack_email_batch_always_includes_one_oversized() -> None:
    counter = _CharCounter()
    limits = BudgetLimits(tpm=500, tpd=1_000_000, body_chars=8000)
    emails = [
        {
            "email_id": "big",
            "sender": "a@b.com",
            "subject": "Huge",
            "body": "x" * 20_000,
            "from_me": False,
        }
    ]
    packed, blocks = pack_email_batch(emails, counter, limits, remaining_tpd=500_000)
    assert len(packed) == 1
    assert blocks[0]
    assert len(blocks[0]) < 20_000


def test_format_analyze_email_block_includes_id() -> None:
    block = format_analyze_email_block(
        {"email_id": "abc", "sender": "a@b.com", "subject": "Hi", "body": "Hello", "from_me": True},
        100,
    )
    assert "ID: abc" in block
    assert "FromMe: True" in block
