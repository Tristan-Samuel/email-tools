"""Natural-language inbox search and structured AI actions."""
from __future__ import annotations

import datetime
import re
from typing import Any

from .ai_client import AiClient

ACTION_TYPES = frozenset(
    {"list_assignments", "waiting_on_me", "this_week", "find_topic", "custom"}
)
QUERY_MODES = frozenset({"search", "action"})


def _extract_keywords_heuristic(prompt: str) -> list[str]:
    stop = {
        "a", "an", "the", "my", "me", "i", "in", "on", "to", "for", "of", "and",
        "or", "about", "find", "list", "show", "give", "emails", "email", "mail",
        "what", "all", "need", "get", "done", "this", "week", "assignments",
        "assignment", "waiting", "reply",
    }
    words = re.findall(r"[a-z0-9']+", prompt.lower())
    return [w for w in words if len(w) > 2 and w not in stop][:8]


def classify_query_heuristic(prompt: str) -> dict[str, Any]:
    p = prompt.lower().strip()
    keywords = _extract_keywords_heuristic(prompt)
    if any(x in p for x in ("assignment", "homework", "due date", "get done", "need to do")):
        if any(x in p for x in ("list", "what", "show", "give me", "all", "need")):
            return {"mode": "action", "action_type": "list_assignments", "keywords": keywords}
    if "waiting on me" in p or "need to reply" in p or "waiting on" in p:
        return {"mode": "action", "action_type": "waiting_on_me", "keywords": keywords}
    if "this week" in p:
        return {"mode": "action", "action_type": "this_week", "keywords": keywords}
    if any(x in p for x in ("list", "summarize", "extract", "give me a list")):
        return {"mode": "action", "action_type": "custom", "keywords": keywords}
    return {"mode": "search", "action_type": "find_topic", "keywords": keywords}


def classify_query(ai: AiClient, prompt: str) -> dict[str, Any]:
    if ai.enabled:
        result = ai.classify_inbox_query(prompt)
        if result:
            return result
    return classify_query_heuristic(prompt)


def rerank_candidates(
    emails: list[dict],
    *,
    keywords: list[str] | None = None,
    action_type: str = "find_topic",
) -> list[dict]:
    today = datetime.date.today()
    kw = [k.lower() for k in (keywords or []) if k]

    def score(email: dict) -> float:
        s = float(email.get("urgency") or email.get("priority_score") or 0)
        intent = (email.get("intent") or "").lower()
        if action_type == "list_assignments":
            if intent == "deadline":
                s += 40
            if email.get("due_at"):
                s += 30
        elif action_type == "waiting_on_me":
            if intent == "i_owe":
                s += 50
        elif action_type == "this_week":
            if email.get("due_at"):
                try:
                    due = datetime.date.fromisoformat(str(email["due_at"])[:10])
                    delta = (due - today).days
                    if 0 <= delta <= 7:
                        s += 50 - delta
                except ValueError:
                    pass
        blob = " ".join(
            [
                str(email.get("subject") or ""),
                str(email.get("line_summary") or ""),
                " ".join(email.get("bullet_summary") or []),
                str(email.get("preview") or ""),
            ]
        ).lower()
        for word in kw:
            if word in blob:
                s += 12
        return s

    return sorted(emails, key=score, reverse=True)


def retrieve_candidates(
    store: Any,
    user_email: str,
    *,
    keywords: list[str] | None = None,
    action_type: str = "find_topic",
    source_account: str | None = None,
    limit: int = 80,
) -> list[dict]:
    """Union FTS, tag/intent heuristics, then rerank — no keyword hits required first."""
    seen: dict[str, dict] = {}

    def add_rows(rows: list[dict]) -> None:
        for row in rows:
            eid = row.get("email_id")
            if eid and eid not in seen:
                seen[eid] = row

    for term in keywords or []:
        if len(term) < 2:
            continue
        add_rows(
            store.search(
                term,
                limit=40,
                user_email=user_email,
                source_account=source_account,
                sort="urgency",
            )
        )

    add_rows(
        store.list_ai_intent_candidates(
            user_email,
            action_type=action_type,
            source_account=source_account,
            limit=limit,
        )
    )

    if not seen:
        add_rows(
            store.list_emails(
                limit=40,
                user_email=user_email,
                source_account=source_account,
                sort="urgency",
            )
        )

    ranked = rerank_candidates(
        list(seen.values()),
        keywords=keywords,
        action_type=action_type,
    )
    return ranked[:limit]


def run_inbox_query(
    store: Any,
    ai: AiClient,
    user_email: str,
    prompt: str,
    *,
    source_account: str | None = None,
) -> dict[str, Any]:
    """Return structured search or action result for templates."""
    prompt = (prompt or "").strip()
    if not prompt:
        return {"ok": False, "error": "Enter a question or action."}

    classification = classify_query(ai, prompt)
    mode = classification.get("mode") or "search"
    action_type = classification.get("action_type") or "find_topic"
    keywords = classification.get("keywords") or _extract_keywords_heuristic(prompt)

    candidates = retrieve_candidates(
        store,
        user_email,
        keywords=keywords,
        action_type=action_type,
        source_account=source_account,
    )

    if not candidates:
        return {
            "ok": True,
            "mode": mode,
            "action_type": action_type,
            "prompt": prompt,
            "emails": [],
            "answer": None,
            "action_items": [],
            "empty": True,
        }

    if mode == "action":
        today = datetime.date.today().isoformat()
        items, err = ai.extract_action_items(prompt, action_type, candidates, today=today)
        if items and action_type == "list_assignments":
            store.upsert_assignment_items(user_email, items)
        return {
            "ok": err is None or bool(items),
            "mode": "action",
            "action_type": action_type,
            "prompt": prompt,
            "emails": candidates[:20],
            "answer": None,
            "action_items": items,
            "error": err,
            "empty": not items,
        }

    if not ai.enabled:
        return {
            "ok": True,
            "mode": "search",
            "action_type": action_type,
            "prompt": prompt,
            "emails": candidates[:50],
            "answer": None,
            "action_items": [],
            "empty": False,
        }

    answer = ai.answer_about_emails(prompt, candidates[:30])
    return {
        "ok": answer is not None,
        "mode": "search",
        "action_type": action_type,
        "prompt": prompt,
        "emails": candidates[:50],
        "answer": answer,
        "action_items": [],
        "error": ai.last_error if answer is None else None,
        "empty": False,
    }
