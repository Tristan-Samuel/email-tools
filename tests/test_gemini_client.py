"""Tests for GeminiClient JSON parsing and model fallback."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.gemini_client import (
    DEFAULT_GEMINI_MODEL,
    GeminiClient,
    _response_text,
    resolve_gemini_model,
)
from app.services.groq_client import _parse_json_content
from app.services.token_budget import BudgetLimits


def test_resolve_gemini_model_remaps_retired_2_5() -> None:
    assert resolve_gemini_model("") == DEFAULT_GEMINI_MODEL
    assert resolve_gemini_model("gemini-2.5-flash-lite") == "gemini-3.5-flash-lite"
    assert resolve_gemini_model("models/gemini-2.5-flash") == "gemini-3.6-flash"
    assert resolve_gemini_model("gemini-3.5-flash-lite") == "gemini-3.5-flash-lite"


def test_retired_default_model_is_remapped() -> None:
    client = GeminiClient(api_key="test-key", default_model="gemini-2.5-flash-lite")
    assert client.default_model == "gemini-3.5-flash-lite"
    assert "gemini-2.5-flash" not in client._models_to_try()


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
    client = GeminiClient(api_key="test-key", default_model="gemini-3.5-flash-lite")
    result = client.analyze_emails_batch(
        [{"email_id": "abc", "sender": "a@b", "subject": "Invoice", "body": "Please pay"}],
        blocks=["ID: abc\nFrom: a@b\nSubject: Invoice\nFromMe: False\nBody:\nPlease pay"],
    )
    assert result["abc"]["bullets"][0] == "Pay the invoice"
    assert result["abc"]["intent"] == "deadline"
    assert "line" in result["abc"]
    assert "compact" in result["abc"]


def test_generate_json_skips_404_model_on_retry() -> None:
    client = GeminiClient(api_key="test-key", default_model="gemini-3.5-flash-lite")
    models = MagicMock()
    models.generate_content.side_effect = [
        Exception("404 NOT_FOUND. This model models/gemini-3.5-flash-lite is no longer available"),
        SimpleNamespace(
            text='{"ok": true}',
            usage_metadata=SimpleNamespace(total_token_count=9),
        ),
    ]
    client._client = SimpleNamespace(models=models)

    parsed, err, tokens = client._generate_json('{"prompt": true}')

    assert err is None
    assert parsed == {"ok": True}
    assert tokens == 9
    assert client.last_model_used == "gemini-3.1-flash-lite"
    assert "gemini-3.5-flash-lite" in client._unavailable_models
    assert client._models_to_try()[0] == "gemini-3.1-flash-lite"
    assert models.generate_content.call_count == 2


def test_generate_json_omits_thinking_config() -> None:
    client = GeminiClient(api_key="test-key", default_model="gemini-3.5-flash-lite")
    models = MagicMock()
    models.generate_content.return_value = SimpleNamespace(
        text='{"ok": true}',
        usage_metadata=SimpleNamespace(total_token_count=1),
    )
    client._client = SimpleNamespace(models=models)
    client._generate_json('{"prompt": true}')
    config = models.generate_content.call_args.kwargs["config"]
    assert getattr(config, "thinking_config", None) is None


def test_generate_json_stops_on_invalid_argument() -> None:
    client = GeminiClient(api_key="test-key", default_model="gemini-3.5-flash-lite")
    models = MagicMock()
    models.generate_content.side_effect = Exception(
        "400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': 'Request contains an invalid argument.', 'status': 'INVALID_ARGUMENT'}}"
    )
    client._client = SimpleNamespace(models=models)
    parsed, err, tokens = client._generate_json('{"prompt": true}')
    assert parsed is None
    assert tokens == 0
    assert err is not None and "INVALID_ARGUMENT" in err
    assert models.generate_content.call_count == 1


def test_response_text_skips_thought_parts() -> None:
    response = SimpleNamespace(
        text='thinking{"ok": true}',
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(thought=True, text="thinking"),
                        SimpleNamespace(thought=False, text='{"ok": true}'),
                    ]
                )
            )
        ],
    )
    assert _response_text(response) == '{"ok": true}'


def test_parse_json_content_extracts_object_and_list() -> None:
    assert _parse_json_content('Sure.\n{"ok": true}\n') == {"ok": True}
    assert _parse_json_content('[{"id": "abc"}]') == {"items": [{"id": "abc"}]}
    assert _parse_json_content('```json\n{"ok": true}\n```\ntrailer') == {"ok": True}


def test_generate_json_parses_thought_prefixed_payload() -> None:
    client = GeminiClient(api_key="test-key", default_model="gemini-3.5-flash-lite")
    models = MagicMock()
    models.generate_content.return_value = SimpleNamespace(
        text='reasoning{"ok": true}',
        usage_metadata=SimpleNamespace(total_token_count=4),
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(thought=True, text="reasoning"),
                        SimpleNamespace(thought=None, text='{"ok": true}'),
                    ]
                )
            )
        ],
    )
    client._client = SimpleNamespace(models=models)
    parsed, err, tokens = client._generate_json('{"prompt": true}')
    assert err is None
    assert parsed == {"ok": True}
    assert tokens == 4


def test_analyze_emails_batch_requests_output_headroom() -> None:
    client = GeminiClient(api_key="test-key", default_model="gemini-3.5-flash-lite")
    models = MagicMock()
    models.generate_content.return_value = SimpleNamespace(
        text='{"items": []}',
        usage_metadata=SimpleNamespace(total_token_count=1),
        candidates=[],
    )
    client._client = SimpleNamespace(models=models)
    emails = [
        {"email_id": str(i), "sender": "a@b", "subject": "S", "body": "B"}
        for i in range(45)
    ]
    client.analyze_emails_batch(emails, blocks=["x"] * 45)
    config = models.generate_content.call_args.kwargs["config"]
    limits = BudgetLimits()
    assert config.max_output_tokens >= limits.max_output_budget()
    assert config.max_output_tokens >= 45 * limits.tokens_per_email_output

