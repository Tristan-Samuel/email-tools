"""Tests for AiClient Gemini-primary / Groq-fallback facade."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.services.ai_client import AiClient
from app.services.gemini_client import GeminiClient
from app.services.groq_client import GroqClient
from app.services.token_budget import BudgetLimits


@patch("app.services.groq_client.requests.post")
def test_ai_client_falls_back_to_groq_on_gemini_failure(mock_post: MagicMock) -> None:
    groq_response = MagicMock(status_code=200, ok=True)
    groq_response.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "items": [
                                {
                                    "id": "abc",
                                    "bullets": ["Reply today"],
                                    "intent": "i_owe",
                                    "reason": "",
                                    "due_at": "",
                                    "tags": [],
                                }
                            ]
                        }
                    )
                }
            }
        ]
    }
    mock_post.return_value = groq_response

    gemini = GeminiClient(api_key="gemini-key", default_model="gemini-3.5-flash-lite")
    groq = GroqClient(api_key="gsk_test", default_model="openai/gpt-oss-20b")
    groq._cached_best_model = "openai/gpt-oss-20b"

    def fake_gemini_batch(*_args, **_kwargs):
        gemini.last_error = "429 rate limit"
        return {}

    with patch.object(GeminiClient, "analyze_emails_batch", side_effect=fake_gemini_batch):
        ai = AiClient(gemini=gemini, groq=groq)
        result = ai.analyze_emails_batch(
            [{"email_id": "abc", "sender": "a@b", "subject": "Hi", "body": "Please reply"}]
        )

    assert "abc" in result
    assert ai.last_provider == "groq"


def test_ai_client_uses_groq_when_no_gemini_key() -> None:
    gemini = GeminiClient(api_key="", default_model="gemini-3.5-flash-lite")
    groq = GroqClient(api_key="gsk_test", default_model="openai/gpt-oss-20b")
    ai = AiClient(gemini=gemini, groq=groq)
    assert ai.enabled
    assert not ai.gemini_enabled
    assert ai.groq_enabled


@patch("app.services.ai_client.TokenCounter")
@patch("app.services.ai_client.pack_email_batch")
def test_packing_keeps_gemini_after_invalid_json(mock_pack, _mock_counter) -> None:
    emails = [
        {"email_id": f"id-{i}", "sender": "a@b", "subject": "S", "body": "B"}
        for i in range(8)
    ]
    mock_pack.side_effect = lambda remaining, *_args, **_kwargs: (
        remaining[:8],
        [f"block-{e['email_id']}" for e in remaining[:8]],
    )

    gemini = GeminiClient(api_key="gemini-key", default_model="gemini-3.5-flash-lite")
    groq = GroqClient(api_key="", default_model="openai/gpt-oss-20b")
    ai = AiClient(gemini=gemini, groq=groq)
    store = MagicMock()
    store.get_kv.return_value = "0"

    def fake_batch(packed, blocks=None, batch_size=8):
        if len(packed) > 2:
            gemini.last_error = "Gemini returned invalid JSON."
            gemini.last_tokens_used = 12
            return {}
        gemini.last_error = ""
        gemini.last_tokens_used = 6
        return {
            packed[0]["email_id"]: {
                "bullets": ["ok"],
                "line": "ok",
                "compact": "ok",
                "intent": "fyi",
                "reason": "",
                "due_at": "",
                "tags": [],
            }
        }

    with patch.object(GeminiClient, "analyze_emails_batch", side_effect=fake_batch):
        batches = list(
            ai.analyze_with_token_packing(
                emails,
                store,
                "me@example.com",
                limits=BudgetLimits(rpm=10_000),
            )
        )

    analyzed_ids = {eid for _chunk, results, _tokens in batches for eid in results}
    assert analyzed_ids
    assert ai.gemini_enabled
    assert ai.last_provider == "gemini"


@patch("app.services.ai_client.TokenCounter")
@patch("app.services.ai_client.pack_email_batch")
def test_packing_disables_gemini_on_rate_limit(mock_pack, _mock_counter) -> None:
    emails = [{"email_id": "id-1", "sender": "a@b", "subject": "S", "body": "B"}]
    mock_pack.return_value = (emails, ["block-id-1"])
    gemini = GeminiClient(api_key="gemini-key", default_model="gemini-3.5-flash-lite")
    groq = GroqClient(api_key="gsk_test", default_model="openai/gpt-oss-20b")
    ai = AiClient(gemini=gemini, groq=groq)
    store = MagicMock()
    store.get_kv.return_value = "0"

    def fake_batch(*_args, **_kwargs):
        gemini.last_error = "429 RESOURCE_EXHAUSTED"
        gemini.last_tokens_used = 0
        return {}

    with patch.object(GeminiClient, "analyze_emails_batch", side_effect=fake_batch):
        batches = list(
            ai.analyze_with_token_packing(
                emails,
                store,
                "me@example.com",
                limits=BudgetLimits(rpm=10_000),
            )
        )

    assert batches == []
    assert not ai.gemini_enabled

