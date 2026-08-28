"""Tests for ai_query classification and retrieval."""
from __future__ import annotations

from app.services.ai_query import classify_query_heuristic, rerank_candidates


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
