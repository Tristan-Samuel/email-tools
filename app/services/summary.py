from __future__ import annotations

import hashlib
import re
from collections import Counter

from .groq_client import GroqClient


STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "with",
    "your",
    "you",
}

ACTION_WORDS = {
    "action",
    "approve",
    "asap",
    "deadline",
    "due",
    "follow",
    "meeting",
    "payment",
    "reply",
    "required",
    "review",
    "schedule",
    "urgent",
}

CATEGORY_RULES = {
    "Urgent": ["urgent", "asap", "immediately", "deadline", "overdue", "today"],
    "Finance": ["invoice", "payment", "receipt", "billing", "refund", "quote"],
    "Work": ["project", "meeting", "proposal", "client", "report", "roadmap"],
    "Alerts": ["alert", "security", "warning", "failed", "incident", "verify"],
    "Newsletters": ["newsletter", "digest", "edition", "weekly", "unsubscribe"],
    "Marketing": ["offer", "discount", "sale", "promo", "webinar", "campaign"],
    "Personal": ["family", "friend", "party", "trip", "dinner", "weekend"],
}

WORD_RE = re.compile(r"[A-Za-z0-9']+")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
DATE_RE = re.compile(r"\b(?:mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", re.I)


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in WORD_RE.findall(text)]


def choose_category(subject: str, body: str) -> tuple[str, int]:
    haystack = f"{subject} {body}".lower()
    best_category = "Other"
    best_score = 15

    for category, keywords in CATEGORY_RULES.items():
        score = sum(1 for keyword in keywords if keyword in haystack)
        if score > 0:
            weighted = min(95, 25 + score * 18)
            if weighted > best_score:
                best_category = category
                best_score = weighted

    if any(keyword in haystack for keyword in CATEGORY_RULES["Urgent"]):
        best_score = max(best_score, 85)

    return best_category, best_score


def extract_keywords(subject: str, body: str, limit: int = 8) -> list[str]:
    tokens = [token for token in tokenize(f"{subject} {body}") if token not in STOP_WORDS and len(token) > 2]
    return [word for word, _ in Counter(tokens).most_common(limit)]


def sentence_score(sentence: str, frequencies: Counter) -> float:
    tokens = tokenize(sentence)
    if not tokens:
        return 0.0

    score = sum(frequencies.get(token, 0) for token in tokens)
    score += sum(3 for token in tokens if token in ACTION_WORDS)
    if DATE_RE.search(sentence):
        score += 2
    return score / max(len(tokens), 1)


def summarize_email(sender: str, subject: str, body: str) -> list[str]:
    sentences = [sentence.strip() for sentence in SENTENCE_RE.split(body) if sentence.strip()]
    tokens = [token for token in tokenize(body) if token not in STOP_WORDS and len(token) > 2]
    frequencies = Counter(tokens)

    bullets = []
    sender_label = sender or "Unknown sender"
    bullets.append(f"{sender_label} is writing about {subject}.")

    if DATE_RE.search(body):
        bullets.append("The message references a date or scheduling detail worth checking.")

    top_sentences = sorted(sentences, key=lambda sentence: sentence_score(sentence, frequencies), reverse=True)
    for sentence in top_sentences[:3]:
        compact = sentence.replace("\n", " ").strip()
        if compact and compact not in bullets:
            bullets.append(compact)

    if len(bullets) < 3 and body:
        snippet = body[:220].strip()
        bullets.append(snippet + ("..." if len(body) > 220 else ""))

    return bullets[:4]


def summarize_email_with_groq(
    sender: str,
    subject: str,
    body: str,
    groq_client: GroqClient | None,
) -> list[str]:
    if groq_client is not None and groq_client.enabled:
        groq_bullets = groq_client.summarize_email(sender=sender, subject=subject, body=body)
        if groq_bullets:
            return groq_bullets

    return summarize_email(sender=sender, subject=subject, body=body)


def preview_text(body: str, limit: int = 180) -> str:
    compact = " ".join(body.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def build_email_record(message: dict, source_name: str, user_email: str, groq_client: GroqClient | None = None) -> dict:
    category, priority_score = choose_category(message["subject"], message["body"])
    keywords = extract_keywords(message["subject"], message["body"])
    bullet_summary = summarize_email_with_groq(
        message["sender"],
        message["subject"],
        message["body"],
        groq_client,
    )
    search_blob = " ".join(
        [
            message["subject"],
            message["sender"],
            message["recipient"],
            message["body"],
            " ".join(bullet_summary),
            " ".join(keywords),
            category,
        ]
    )

    scoped_email_id = hashlib.sha1(f"{user_email}|{message['email_id']}".encode("utf-8")).hexdigest()

    return {
        "email_id": scoped_email_id,
        "message_id": message["message_id"],
        "source_name": source_name,
        "user_email": user_email,
        "subject": message["subject"],
        "sender": message["sender"],
        "recipient": message["recipient"],
        "cc": message["cc"],
        "received_at": message["received_at"],
        "body": message["body"],
        "preview": preview_text(message["body"]),
        "bullet_summary": bullet_summary,
        "category": category,
        "priority_score": priority_score,
        "keywords": keywords,
        "search_blob": search_blob,
    }


def build_digest(emails: list[dict]) -> dict:
    if not emails:
        return {
            "headline": "No email has been analyzed yet.",
            "bullets": ["Upload .eml or .mbox files to build a searchable, summarized inbox."],
        }

    categories = Counter(email["category"] for email in emails)
    urgent = [email for email in emails if email["priority_score"] >= 80]
    senders = Counter(email["sender"] or "Unknown sender" for email in emails)

    bullets = [
        f"{len(urgent)} messages look urgent or deadline-driven.",
        f"The busiest category is {categories.most_common(1)[0][0]} with {categories.most_common(1)[0][1]} emails.",
        f"Most frequent sender: {senders.most_common(1)[0][0]}.",
    ]

    for email in emails[:3]:
        summary_line = email["bullet_summary"][1] if len(email["bullet_summary"]) > 1 else email["preview"]
        bullets.append(f"{email['subject']}: {summary_line}")

    return {
        "headline": "Inbox brief generated from cached email summaries.",
        "bullets": bullets[:6],
    }