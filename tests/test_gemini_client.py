"""Tests for GeminiClient JSON parsing."""
from __future__ import annotations

from unittest.mock import patch

from app.services.gemini_client import GeminiClient


@patch.object(GeminiClient, "_generate_json")
def test_analyze_emails_batch_parses_items(mock_generate) -> None:
    mock_generate.return_value = (
        {
            "items": [
                {
                    "id": "abc",
                    "bullets": ["Pay the invoice"],
                    "intent": "deadline",
                    "reason": "Due Friday",
                    "due_at": "2026-08-29",
                    "tags": [],
                }
            ]
        },
        None,
        42,
    )
    client = GeminiClient(api_key="test-key", default_model="gemini-2.5-flash-lite")
    result = client.analyze_emails_batch(
        [{"email_id": "abc", "sender": "a@b", "subject": "Invoice", "body": "Please pay"}],
        blocks=["ID: abc\nFrom: a@b\nSubject: Invoice\nFromMe: False\nBody:\nPlease pay"],
    )
    assert result["abc"]["bullets"][0] == "Pay the invoice"
    assert result["abc"]["intent"] == "deadline"
    assert "line" in result["abc"]
    assert "compact" in result["abc"]
