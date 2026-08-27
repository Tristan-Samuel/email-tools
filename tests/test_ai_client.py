"""Tests for AiClient Gemini-primary / Groq-fallback facade."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from app.services.ai_client import AiClient
from app.services.gemini_client import GeminiClient
from app.services.groq_client import GroqClient


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

    gemini = GeminiClient(api_key="gemini-key", default_model="gemini-2.5-flash-lite")
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
    gemini = GeminiClient(api_key="", default_model="gemini-2.5-flash-lite")
    groq = GroqClient(api_key="gsk_test", default_model="openai/gpt-oss-20b")
    ai = AiClient(gemini=gemini, groq=groq)
    assert ai.enabled
    assert not ai.gemini_enabled
    assert ai.groq_enabled
