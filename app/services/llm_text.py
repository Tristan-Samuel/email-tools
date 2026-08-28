"""Shared text compaction for LLM prompts — no imports from provider clients."""
from __future__ import annotations

import re
from typing import Any

ANGLE_URL_RE = re.compile(r"<(https?://[^>\s]+|mailto:[^>\s]+)>", re.I)
RAW_URL_RE = re.compile(r"(https?://[^\s<>\"']+)", re.I)
LABEL_ANGLE_URL_RE = re.compile(r"([^<\n]+?)\s*<(https?://[^>\s]+)>", re.I)
UTM_PARAM_RE = re.compile(r"[?&]utm_[^&\s]+", re.I)
_ID_PAREN_RE = re.compile(r"\s*\(?\s*ID:\s*[0-9a-f]{8,}\s*\)?\s*", re.I)
_SHA1_RE = re.compile(r"\b[0-9a-f]{40}\b", re.I)
_KEY_ACTIONS_RE = re.compile(r"^key actions:\s*", re.I)
_EMAIL_INDEX_RE = re.compile(r"(?:email\s*)?#\s*(\d+)\b", re.I)

ACTION_EXTRACT_SYSTEM = (
    "Extract actionable items from the emails for the user's request. "
    'Return JSON: {"items": [{"email": 1, "title": "short human task title", '
    '"due_at": "YYYY-MM-DD or empty", "status": "open"}]}. '
    "email is the Email # number from the list. "
    "Titles must be short and human — never include IDs, hashes, or an 'ID:' suffix. "
    "Do not write a Key actions heading or a comma-separated teaser. "
    "Only include items clearly supported by the emails."
)

DIGEST_SYSTEM = (
    "You write inbox briefs for email triage. Return JSON with "
    '"headline" (one short sentence — never a "Key actions:" teaser or comma list) '
    'and "bullets" (up to 6 objects with "text" and "id"). '
    "Put the email ID only in id, never in headline or text. No hashes. "
    "Prioritize deadlines, action items, and urgent mail. No raw URLs in angle brackets."
)


def compact_for_llm(text: str, limit: int = 800) -> str:
    """Strip URLs and tracking noise before sending text to Groq."""
    if not text:
        return ""
    cleaned = LABEL_ANGLE_URL_RE.sub(lambda m: m.group(1).strip(), text)
    cleaned = ANGLE_URL_RE.sub("", cleaned)
    cleaned = RAW_URL_RE.sub("", cleaned)
    cleaned = UTM_PARAM_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" |")
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(limit - 3, 0)].rstrip() + "..."


def sanitize_action_title(title: str) -> str:
    """Strip model-copied email hashes from a human-facing task title."""
    text = (title or "").strip()
    text = _ID_PAREN_RE.sub(" ", text)
    text = _SHA1_RE.sub(" ", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip(" \t-–—.,;:")


def sanitize_digest_headline(text: str) -> str:
    """Drop Key-actions teasers and hashes from a digest headline."""
    line = sanitize_action_title(text)
    if _KEY_ACTIONS_RE.match(line):
        rest = _KEY_ACTIONS_RE.sub("", line).strip()
        if not rest or ("," in rest and len(rest) < 220):
            return ""
        return rest
    return line


def clean_inbox_digest(parsed: Any) -> dict | None:
    """Normalize a digest JSON object; strip IDs from display text."""
    if not isinstance(parsed, dict):
        return None
    cleaned_bullets: list[dict[str, str]] = []
    raw_bullets = parsed.get("bullets") or []
    if isinstance(raw_bullets, list):
        for item in raw_bullets:
            if isinstance(item, dict):
                text = sanitize_action_title(str(item.get("text") or item.get("bullet") or ""))
                eid = str(item.get("id") or item.get("email_id") or "").strip()
                if text:
                    cleaned_bullets.append({"text": text, "email_id": eid})
            elif isinstance(item, str) and item.strip():
                text = sanitize_action_title(item)
                if text:
                    cleaned_bullets.append({"text": text, "email_id": ""})
    headline = sanitize_digest_headline(str(parsed.get("headline") or ""))
    if not headline and cleaned_bullets:
        headline = cleaned_bullets[0]["text"]
    if headline and cleaned_bullets:
        return {"headline": headline, "bullets": cleaned_bullets[:6]}
    return None


def format_action_email_blocks(emails: list[dict], limit: int = 30) -> str:
    """Numbered email context for action extraction — no SHA-1 ids."""
    parts: list[str] = []
    for i, email in enumerate(emails[:limit], 1):
        bullets = email.get("bullet_summary") or []
        summary = " ".join(bullets) if bullets else (email.get("preview") or "")
        parts.append(
            f"Email #{i}\n"
            f"Date: {email.get('received_at', 'unknown')}\n"
            f"Due: {email.get('due_at') or 'unknown'}\n"
            f"From: {email.get('sender', '?')}\n"
            f"Subject: {email.get('subject', '?')}\n"
            f"Summary: {summary}"
        )
    return "\n\n---\n\n".join(parts)


def resolve_extracted_email_id(raw: Any, emails: list[dict]) -> str:
    """Map Email #n / leftover hashes back to a real email_id."""
    known = {str(e.get("email_id") or "") for e in emails if e.get("email_id")}
    if isinstance(raw, int) and 1 <= raw <= len(emails):
        return str(emails[raw - 1].get("email_id") or "")
    text = str(raw or "").strip()
    if not text:
        return ""
    if text in known:
        return text
    match = _EMAIL_INDEX_RE.search(text) or re.fullmatch(r"(\d+)", text)
    if match:
        idx = int(match.group(1))
        if 1 <= idx <= len(emails):
            return str(emails[idx - 1].get("email_id") or "")
    return ""


def _email_meta(email_id: str, emails: list[dict]) -> dict[str, str]:
    for email in emails:
        if str(email.get("email_id") or "") == email_id:
            return {
                "sender": str(email.get("sender") or ""),
                "subject": str(email.get("subject") or ""),
            }
    return {"sender": "", "subject": ""}


def clean_extracted_action_items(raw_items: Any, emails: list[dict]) -> list[dict]:
    """Normalize model JSON into {email_id, title, due_at, status, sender, subject}."""
    if not isinstance(raw_items, list):
        return []
    cleaned: list[dict] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        eid = resolve_extracted_email_id(
            item.get("email") if item.get("email") not in (None, "") else item.get("email_id"),
            emails,
        )
        title = sanitize_action_title(str(item.get("title") or item.get("reason") or ""))
        if not eid or not title or eid in seen:
            continue
        seen.add(eid)
        due = str(item.get("due_at") or item.get("due_date") or "")[:10]
        meta = _email_meta(eid, emails)
        cleaned.append(
            {
                "email_id": eid,
                "title": title,
                "due_at": due or None,
                "status": "open",
                "sender": meta["sender"],
                "subject": meta["subject"],
            }
        )
    return cleaned


def split_ai_answer(text: str) -> list[str]:
    """Turn a prose AI answer into display blocks; drop ID dumps and teaser headers."""
    if not (text or "").strip():
        return []
    blocks: list[str] = []
    for raw_line in text.splitlines():
        line = _ID_PAREN_RE.sub(" ", raw_line)
        line = _SHA1_RE.sub(" ", line)
        line = re.sub(r"\s{2,}", " ", line).strip(" \t-–—•*")
        if not line:
            continue
        if _KEY_ACTIONS_RE.match(line):
            rest = _KEY_ACTIONS_RE.sub("", line).strip()
            if not rest or ("," in rest and len(rest) < 220):
                continue
            line = rest
        blocks.append(line)
    return blocks
