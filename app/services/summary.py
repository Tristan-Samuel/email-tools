from __future__ import annotations

import hashlib
import html as html_module
import re
from collections import Counter
from markupsafe import Markup

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
    "School": ["homework", "assignment", "lecture", "professor", "university", "college",
               "course", "exam", "grade", "syllabus", "campus", "tutor", "canvas",
               "moodle", "blackboard", "curriculum", "semester", "student", "enroll"],
    "Alerts": ["alert", "security", "warning", "failed", "incident", "verify"],
    "Newsletters": ["newsletter", "digest", "edition", "weekly", "unsubscribe"],
    "Marketing": ["offer", "discount", "sale", "promo", "webinar", "campaign"],
    "Personal": ["family", "friend", "party", "trip", "dinner", "weekend"],
}

WORD_RE = re.compile(r"[A-Za-z0-9']+")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
DATE_RE = re.compile(
    r"\b(?:mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b",
    re.I,
)
SUBJECT_PREFIX_RE = re.compile(r"^(?:(?:re|fwd?|fw)\s*:\s*)+", re.I)
ANGLE_URL_RE = re.compile(r"<(https?://[^>\s]+|mailto:[^>\s]+)>", re.I)
RAW_URL_RE = re.compile(r"(https?://[^\s<>\"']+)", re.I)
FOOTER_JUNK_RE = re.compile(
    r"(Email me a question|Admissions|Tours|Unsubscribe|View in browser).*$",
    re.I,
)
LABEL_ANGLE_URL_RE = re.compile(r"([^<\n]+?)\s*<(https?://[^>\s]+)>", re.I)


def compact_for_llm(text: str, limit: int = 800) -> str:
    """Strip URLs and tracking noise before sending text to Groq."""
    from .llm_text import compact_for_llm as _compact

    return _compact(text, limit)


def clean_summary_line(text: str, max_len: int = 220) -> str:
    """Strip footer junk and angle-bracket mailto/URL artifacts from a summary line."""
    if not text:
        return ""
    line = ANGLE_URL_RE.sub("", text)
    line = FOOTER_JUNK_RE.sub("", line)
    line = re.sub(r"\s+", " ", line).strip(" |")
    if len(line) > max_len:
        line = line[: max_len - 3].rstrip() + "..."
    return line


def extract_links_from_text(text: str, limit: int = 5) -> list[dict[str, str]]:
    """Return safe https/mailto links found in plain text."""
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in ANGLE_URL_RE.finditer(text or ""):
        url = match.group(1).strip()
        if url in seen:
            continue
        if url.lower().startswith("https://") or url.lower().startswith("http://") or url.lower().startswith("mailto:"):
            seen.add(url)
            label = url.split("://", 1)[-1][:48]
            links.append({"url": url, "label": label})
            if len(links) >= limit:
                return links
    for match in RAW_URL_RE.finditer(text or ""):
        url = match.group(1).rstrip(".,)")
        if url in seen:
            continue
        if url.lower().startswith("http"):
            seen.add(url)
            links.append({"url": url, "label": url[:48]})
            if len(links) >= limit:
                break
    return links


def sanitize_bullet_text(text: str) -> str | Markup:
    """Escape text and linkify safe URLs for display in templates."""
    if not text:
        return ""
    cleaned = clean_summary_line(text, max_len=500)
    escaped = html_module.escape(cleaned)
    def _linkify(match: re.Match[str]) -> str:
        url = match.group(1)
        safe = html_module.escape(url)
        return f'<a href="{safe}" target="_blank" rel="noopener noreferrer">{safe[:60]}</a>'

    escaped = ANGLE_URL_RE.sub(lambda m: _linkify(m), escaped)
    escaped = RAW_URL_RE.sub(lambda m: _linkify(m), escaped)
    return Markup(escaped)


def normalize_thread_subject(subject: str) -> str:
    cleaned = SUBJECT_PREFIX_RE.sub("", subject or "").strip()
    return cleaned.lower() or "(no subject)"


def compute_thread_id(message: dict) -> str:
    """Stable thread key from In-Reply-To / References, else normalized subject."""
    in_reply_to = (message.get("in_reply_to") or "").strip()
    if in_reply_to:
        return hashlib.sha1(in_reply_to.encode("utf-8")).hexdigest()
    references = (message.get("references") or "").strip()
    if references:
        first_ref = references.split()[0]
        if first_ref:
            return hashlib.sha1(first_ref.encode("utf-8")).hexdigest()
    message_id = (message.get("message_id") or "").strip()
    if message_id:
        return hashlib.sha1(message_id.encode("utf-8")).hexdigest()
    subject_key = normalize_thread_subject(message.get("subject", ""))
    sender = (message.get("sender") or "").strip().lower()
    return hashlib.sha1(f"{sender}|{subject_key}".encode("utf-8")).hexdigest()


def contains_keyword(haystack: str, keyword: str) -> bool:
    return re.search(rf"\b{re.escape(keyword)}\b", haystack, re.I) is not None


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in WORD_RE.findall(text)]


def choose_category(subject: str, body: str) -> tuple[str, int]:
    haystack = f"{subject} {body}"
    best_category = "Other"
    best_score = 15

    for category, keywords in CATEGORY_RULES.items():
        score = sum(1 for keyword in keywords if contains_keyword(haystack, keyword))
        if score > 0:
            weighted = min(75, 25 + score * 18)
            if weighted > best_score:
                best_category = category
                best_score = weighted

    if any(contains_keyword(haystack, kw) for kw in CATEGORY_RULES["Urgent"]):
        if best_category in ("Newsletters", "Marketing"):
            best_score = max(best_score, 55)
        else:
            best_score = max(best_score, 80)

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

    bullets: list[str] = []
    top_sentences = sorted(sentences, key=lambda sentence: sentence_score(sentence, frequencies), reverse=True)
    for sentence in top_sentences[:3]:
        compact = sentence.replace("\n", " ").strip()
        if compact and compact not in bullets:
            bullets.append(compact)

    if not bullets and not body.strip():
        sender_label = sender or "Unknown sender"
        bullets.append(f"{sender_label} is writing about {subject}.")

    if len(bullets) < 3 and body.strip():
        best_sentence = top_sentences[0] if top_sentences else ""
        if best_sentence and DATE_RE.search(best_sentence) and sentence_score(best_sentence, frequencies) >= 2:
            bullets.append("The message references a date or scheduling detail worth checking.")

    if len(bullets) < 3 and body:
        snippet = body[:220].strip()
        if snippet and snippet not in bullets:
            bullets.append(snippet + ("..." if len(body) > 220 else ""))

    return bullets[:4]


def summarize_email_with_groq(
    sender: str,
    subject: str,
    body: str,
    groq_client: GroqClient | None,
) -> tuple[list[str], bool]:
    """Return (bullets, ai_analyzed). ai_analyzed is True when Groq produced bullets."""
    if groq_client is not None and groq_client.enabled:
        groq_bullets = groq_client.summarize_email(sender=sender, subject=subject, body=body)
        if groq_bullets:
            return groq_bullets, True

    return summarize_email(sender=sender, subject=subject, body=body), False


def preview_text(body: str, limit: int = 180) -> str:
    compact = " ".join(body.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def build_email_record(
    message: dict,
    source_name: str,
    user_email: str,
    groq_client: GroqClient | None = None,
    source_account: str = "",
) -> dict:
    category, priority_score = choose_category(message["subject"], message["body"])
    keywords = extract_keywords(message["subject"], message["body"])
    bullet_summary, ai_analyzed = summarize_email_with_groq(
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

    account_key = source_account or source_name
    scoped_email_id = hashlib.sha1(
        f"{user_email}|{account_key}|{message['email_id']}".encode("utf-8")
    ).hexdigest()

    return {
        "email_id": scoped_email_id,
        "message_id": message["message_id"],
        "in_reply_to": message.get("in_reply_to", ""),
        "thread_id": compute_thread_id(message),
        "source_name": source_name,
        "source_account": source_account,
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
        "is_mailing_list": message.get("is_mailing_list", 0),
        "ai_analyzed": 1 if ai_analyzed else 0,
    }


def build_digest(
    emails: list[dict],
    has_imap_accounts: bool = False,
    groq_client: GroqClient | None = None,
) -> dict:
    if not emails:
        if has_imap_accounts:
            return {
                "headline": "Your inbox is connected.",
                "bullets": [{"text": "Sync to load messages, or browse Inbox when mail arrives.", "email_id": ""}],
                "ai_generated": False,
            }
        return {
            "headline": "Connect your inbox to get started.",
            "bullets": [
                {"text": "Add an IMAP account under Accounts to fetch and summarize your mail.", "email_id": ""},
                {"text": "Optional: import .eml or .mbox files from the Dashboard.", "email_id": ""},
            ],
            "ai_generated": False,
        }

    if groq_client is not None and groq_client.enabled:
        groq_digest = groq_client.build_inbox_digest(emails)
        if groq_digest:
            bullets_out: list[dict[str, str]] = []
            for item in groq_digest.get("bullets", []):
                if isinstance(item, dict):
                    text = clean_summary_line(str(item.get("text") or ""))
                    eid = str(item.get("email_id") or "").strip()
                    if text:
                        bullets_out.append({"text": text, "email_id": eid})
                elif isinstance(item, str):
                    text = clean_summary_line(item)
                    if text:
                        bullets_out.append({"text": text, "email_id": ""})
            return {
                "headline": groq_digest.get("headline", "Inbox brief"),
                "bullets": bullets_out[:6],
                "ai_generated": True,
            }

    categories = Counter(email["category"] for email in emails)
    urgent = [email for email in emails if email["priority_score"] >= 80]
    senders = Counter(email["sender"] or "Unknown sender" for email in emails)

    bullets: list[dict[str, str]] = [
        {"text": f"{len(urgent)} messages look urgent or deadline-driven.", "email_id": ""},
        {
            "text": (
                f"The busiest category is {categories.most_common(1)[0][0]} "
                f"with {categories.most_common(1)[0][1]} emails."
            ),
            "email_id": "",
        },
        {
            "text": f"Most frequent sender: {senders.most_common(1)[0][0].split('<')[0].strip()}.",
            "email_id": "",
        },
    ]

    for email in emails[:3]:
        raw = email["bullet_summary"][0] if email["bullet_summary"] else email["preview"]
        summary_line = clean_summary_line(raw)
        if summary_line:
            bullets.append(
                {
                    "text": f"{email['subject']}: {summary_line}",
                    "email_id": email["email_id"],
                }
            )

    return {
        "headline": "Inbox brief from your cached summaries.",
        "bullets": bullets[:6],
        "ai_generated": False,
    }


def build_important_items(emails: list[dict], limit: int = 8) -> list[dict]:
    """High-priority emails with cleaned one-line summaries and extracted links."""
    urgent = sorted(
        [e for e in emails if e.get("priority_score", 0) >= 75],
        key=lambda x: (-x.get("priority_score", 0), x.get("received_at", "")),
    )[:limit]
    items: list[dict] = []
    for email in urgent:
        raw = email["bullet_summary"][0] if email.get("bullet_summary") else email.get("preview", "")
        blob = " ".join(email.get("bullet_summary") or []) + " " + (email.get("body") or "")[:2000]
        items.append(
            {
                "email_id": email["email_id"],
                "subject": email.get("subject") or "(no subject)",
                "summary": clean_summary_line(raw),
                "links": extract_links_from_text(blob),
            }
        )
    return items
