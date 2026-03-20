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
WHITESPACE_RE = re.compile(r"\s+")


def strip_html(value: str) -> str:
    no_tags = TAG_RE.sub(" ", value)
    return WHITESPACE_RE.sub(" ", html.unescape(no_tags)).strip()


def normalize_text(value: str) -> str:
    return WHITESPACE_RE.sub(" ", value).strip()


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
    plain_parts = []
    html_parts = []

    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = part.get_content_disposition()
            if disposition == "attachment":
                continue

            if content_type == "text/plain":
                plain_parts.append(part.get_content())
            elif content_type == "text/html":
                html_parts.append(part.get_content())
    else:
        content_type = message.get_content_type()
        content = message.get_content()
        if content_type == "text/plain":
            plain_parts.append(content)
        elif content_type == "text/html":
            html_parts.append(content)

    if plain_parts:
        return normalize_text(" ".join(str(part) for part in plain_parts))

    if html_parts:
        return strip_html(" ".join(str(part) for part in html_parts))

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
        "email_id": build_message_id(message, body),
        "message_id": message.get("message-id", "").strip(),
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