"""Tests for ai_query classification and retrieval."""
from __future__ import annotations

from app.services.ai_query import classify_query_heuristic, rerank_candidates
from app.services.llm_text import (
    clean_extracted_action_items,
    sanitize_action_title,
    split_ai_answer,
)


def test_classify_assignments_action() -> None:
    result = classify_query_heuristic("List assignments I need to get done")
    assert result["mode"] == "action"
    assert result["action_type"] == "list_assignments"


def test_classify_find_emails_search() -> None:
    result = classify_query_heuristic("Find emails about biology homework")
    assert result["mode"] == "search"


def test_rerank_prefers_due_dates_for_assignments() -> None:
    emails = [
        {"email_id": "a", "urgency": 10, "intent": "fyi", "subject": "hello"},
        {"email_id": "b", "urgency": 5, "intent": "deadline", "due_at": "2026-09-01", "subject": "due"},
    ]
    ranked = rerank_candidates(emails, action_type="list_assignments")
    assert ranked[0]["email_id"] == "b"


def test_sanitize_action_title_strips_id_suffix() -> None:
    raw = "Submit physics form by Monday (ID: a9690bf176b6f2132dc96cd7c463114373b1a8c9)."
    assert "a9690bf" not in sanitize_action_title(raw)
    assert "physics" in sanitize_action_title(raw).lower()


def test_clean_extracted_items_maps_email_index() -> None:
    emails = [
        {"email_id": "aaa", "sender": "Ada", "subject": "Lab"},
        {"email_id": "bbb", "sender": "Ben", "subject": "Form"},
    ]
    items = clean_extracted_action_items(
        [
            {"email": 2, "title": "Turn in form (ID: a9690bf176b6f2132dc96cd7c463114373b1a8c9)", "due_at": "2026-09-01"},
            {"email_id": "aaa", "title": "Do the lab"},
        ],
        emails,
    )
    assert items[0]["email_id"] == "bbb"
    assert "ID:" not in items[0]["title"]
    assert items[0]["sender"] == "Ben"
    assert items[1]["email_id"] == "aaa"


def test_split_ai_answer_drops_key_actions_teaser() -> None:
    blob = (
        "Key actions: physics docs due Monday, volunteer today\n"
        "Submit physics form by Monday (ID: a9690bf176b6f2132dc96cd7c463114373b1a8c9).\n"
        "Volunteer in the pavilion today."
    )
    blocks = split_ai_answer(blob)
    assert blocks
    assert not any(b.lower().startswith("key actions:") for b in blocks)
    assert not any("a9690bf" in b for b in blocks)
    assert any("pavilion" in b.lower() for b in blocks)
