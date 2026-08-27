from __future__ import annotations

import hashlib
import html
import mailbox
import re
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path


TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"[ \t]+")
MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
A_HREF_RE = re.compile(
    r"<a\s+[^>]*href\s*=\s*['\"]?(https?://[^'\">\s]+|mailto:[^'\">\s]+)['\"]?[^>]*>(.*?)</a>",
    re.I | re.DOTALL,
)
SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.DOTALL)
BLOCK_BREAK_RE = re.compile(r"</?(?:p|div|tr|li|h[1-6]|table|section|article|header|footer)[^>]*>", re.I)
BR_RE = re.compile(r"<br\s*/?>", re.I)
URL_HEAVY_RE = re.compile(r"(?:<)?https?://", re.I)


def strip_html(value: str) -> str:
    """Legacy naive HTML strip — prefer html_to_text for ingest."""
    no_tags = TAG_RE.sub(" ", value)
    return WHITESPACE_RE.sub(" ", html.unescape(no_tags)).strip()


def html_to_text(value: str) -> str:
    """Convert HTML to readable plain text with paragraph breaks and link labels."""
    if not value:
        return ""
    text = SCRIPT_STYLE_RE.sub(" ", value)
    text = A_HREF_RE.sub(lambda m: (m.group(2) or m.group(1) or "").strip(), text)
    text = BR_RE.sub("\n", text)
    text = BLOCK_BREAK_RE.sub("\n", text)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return normalize_body_text(text)


def normalize_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value).strip()


def normalize_body_text(value: str) -> str:
    """Collapse horizontal whitespace but preserve paragraph breaks."""
    if not value:
        return ""
    lines = [WHITESPACE_RE.sub(" ", line).strip() for line in value.replace("\r\n", "\n").split("\n")]
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if line:
            current.append(line)
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    joined = "\n\n".join(paragraphs)
    return MULTI_NEWLINE_RE.sub("\n\n", joined).strip()


def is_url_heavy_plaintext(text: str) -> bool:
    """Return True when plaintext is mostly URL/nav chrome."""
    if not text or len(text) < 80:
        return False
    sample = text[:2000]
    url_hits = len(URL_HEAVY_RE.findall(sample))
    if url_hits >= 4:
        return True
    non_space = len(sample.replace(" ", "").replace("\n", ""))
    if non_space < 50:
        return False
    url_chars = sum(len(m.group(0)) for m in URL_HEAVY_RE.finditer(sample))
    return url_chars / non_space > 0.35


def parse_address_header(value: str | None) -> str:
    if not value:
        return ""

    addresses = getaddresses([value])
    formatted = []
    for display_name, address in addresses:
        if display_name and address:
            formatted.append(f"{display_name} <{address}>")
        elif address:
            formatted.append(address)
        elif display_name:
            formatted.append(display_name)

    return ", ".join(formatted)


def extract_body(message) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = part.get_content_disposition()
            if disposition == "attachment":
                continue

            if content_type == "text/plain":
                plain_parts.append(str(part.get_content()))
            elif content_type == "text/html":
                html_parts.append(str(part.get_content()))
    else:
        content_type = message.get_content_type()
        content = message.get_content()
        if content_type == "text/plain":
            plain_parts.append(str(content))
        elif content_type == "text/html":
            html_parts.append(str(content))

    plain_text = normalize_body_text("\n\n".join(plain_parts)) if plain_parts else ""
    html_text = html_to_text(" ".join(html_parts)) if html_parts else ""

    if plain_text and html_parts and is_url_heavy_plaintext(plain_text):
        return html_text or plain_text
    if plain_text:
        return plain_text
    if html_text:
        return html_text
    return ""


def parsed_timestamp(message) -> str | None:
    value = message.get("date")
    if not value:
        return None

    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def build_message_id(message, body: str) -> str:
    source = "|".join(
        [
            message.get("message-id", ""),
            message.get("subject", ""),
            message.get("from", ""),
            message.get("date", ""),
            body[:4000],
        ]
    )
    return hashlib.sha1(source.encode("utf-8", errors="ignore")).hexdigest()


def message_email_id(message, body: str, fallback: str = "") -> str:
    """Stable id from Message-ID when present, else fallback or header hash."""
    mid = (message.get("message-id") or "").strip()
    if mid:
        return hashlib.sha1(mid.encode("utf-8", errors="replace")).hexdigest()
    if fallback:
        return hashlib.sha1(fallback.encode("utf-8", errors="replace")).hexdigest()
    return build_message_id(message, body)


MAILING_LIST_HEADERS = frozenset([
    "list-id", "list-unsubscribe", "list-post", "list-archive",
    "list-help", "x-mailchimp-id", "x-campaign", "x-mailer",
    "precedence",
])
MAILING_LIST_PRECEDENCE = frozenset(["bulk", "list", "junk"])


def is_mailing_list_message(message) -> bool:
    """Return True if the message looks like a bulk/mailing-list email."""
    for header in MAILING_LIST_HEADERS:
        if message.get(header):
            if header == "precedence":
                if (message.get(header) or "").strip().lower() in MAILING_LIST_PRECEDENCE:
                    return True
            else:
                return True
    return False


def parse_message(message) -> dict:
    body = extract_body(message)
    return {
        "email_id": message_email_id(message, body),
        "message_id": (message.get("message-id") or "").strip(),
        "in_reply_to": (message.get("in-reply-to") or "").strip(),
        "references": (message.get("references") or "").strip(),
        "subject": normalize_text(message.get("subject", "(No subject)")) or "(No subject)",
        "sender": parse_address_header(message.get("from")),
        "recipient": parse_address_header(message.get("to")),
        "cc": parse_address_header(message.get("cc")),
        "received_at": parsed_timestamp(message),
        "body": body,
        "is_mailing_list": 1 if is_mailing_list_message(message) else 0,
    }


def parse_eml(path: Path) -> list[dict]:
    with path.open("rb") as handle:
        message = BytesParser(policy=policy.default).parse(handle)
    return [parse_message(message)]


def parse_mbox(path: Path) -> list[dict]:
    box = mailbox.mbox(path)
    messages = []
    for message in box:
        parsed = BytesParser(policy=policy.default).parsebytes(message.as_bytes())
        messages.append(parse_message(parsed))
    return messages


def parse_email_upload(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".eml":
        return parse_eml(path)
    if suffix == ".mbox":
        return parse_mbox(path)

    raise ValueError(f"Unsupported file type: {path.name}")
