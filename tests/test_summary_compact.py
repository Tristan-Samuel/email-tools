from __future__ import annotations

from app.services.llm_text import compact_for_llm


def test_compact_for_llm_strips_urls_keeps_labels() -> None:
    text = "Visit <https://school.edu/visit?utm_campaign=sp> for tours."
    compact = compact_for_llm(text, 200)
    assert "Visit" in compact
    assert "https://" not in compact
    assert "utm_" not in compact


def test_compact_for_llm_truncates_after_stripping() -> None:
    text = "Hello " + "word " * 200 + "https://example.com/long/path?utm_source=x"
    compact = compact_for_llm(text, 80)
    assert len(compact) <= 83
    assert "https://" not in compact
