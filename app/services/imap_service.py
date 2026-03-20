"""
IMAP email fetching service.

Works with any IMAP-over-SSL server — Gmail, Outlook, Yahoo, etc.
For Gmail use host=imap.gmail.com, port=993 and an App Password
(My Account → Security → 2-Step Verification → App passwords).

Returns email dicts in the same format as email_parser.py so they
can be passed directly to summary.build_email_record().
"""
from __future__ import annotations

import email as email_lib
import imaplib
import ssl
from email import policy
from email.headerregistry import Address
from email.parser import BytesParser


GMAIL_HOST = "imap.gmail.com"
GMAIL_PORT = 993

_PARSER = BytesParser(policy=policy.default)


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _connect(host: str, port: int, username: str, password: str) -> imaplib.IMAP4_SSL:
    ctx = ssl.create_default_context()
    conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
    conn.login(username, password)
    return conn


def test_connection(host: str, port: int, username: str, password: str) -> tuple[bool, str]:
    """Return (ok, error_message)."""
    try:
        conn = _connect(host, port, username, password)
        conn.logout()
        return True, ""
    except imaplib.IMAP4.error as exc:
        return False, str(exc)
    except OSError as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _header_str(msg, name: str) -> str:
    raw = msg.get(name, "")
    try:
        return str(raw)
    except Exception:
        return raw or ""


def _address_str(msg, name: str) -> str:
    raw = msg.get(name)
    if raw is None:
        return ""
    try:
        addrs = msg[name].addresses  # type: ignore[attr-defined]
        return ", ".join(
            str(a.addr_spec) if isinstance(a, Address) else str(a)
            for a in addrs
        )
    except Exception:
        return str(raw)


def _body_text(msg) -> str:
    """Extract plain-text body from a parsed message."""
    if msg.is_multipart():
        plain_parts: list[str] = []
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if ct == "text/plain" and "attachment" not in disp:
                try:
                    plain_parts.append(part.get_content())
                except Exception:
                    pass
        if plain_parts:
            return "\n".join(plain_parts)
        # Fall back to HTML → plain strip
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html":
                try:
                    import html
                    import re
                    raw_html = part.get_content()
                    stripped = re.sub(r"<[^>]+>", " ", raw_html)
                    return html.unescape(stripped)
                except Exception:
                    pass
        return ""
    else:
        try:
            return msg.get_content()
        except Exception:
            return ""


def _parse_raw_bytes(uid_bytes: bytes, raw_bytes: bytes) -> dict | None:
    """Parse raw RFC 2822 bytes into an email dict."""
    try:
        msg = _PARSER.parsebytes(raw_bytes)
    except Exception:
        return None

    import hashlib as _hashlib
    uid_hex = uid_bytes.decode() if isinstance(uid_bytes, bytes) else str(uid_bytes)
    message_id = _header_str(msg, "Message-ID").strip() or uid_hex
    email_id = _hashlib.sha1(message_id.encode("utf-8", errors="replace")).hexdigest()

    subject = _header_str(msg, "Subject") or "(no subject)"
    sender = _address_str(msg, "From") or _header_str(msg, "From")
    recipient = _address_str(msg, "To") or _header_str(msg, "To") or ""
    cc = _address_str(msg, "Cc") or _header_str(msg, "Cc") or ""

    raw_date = _header_str(msg, "Date")
    received_at: str | None = None
    if raw_date:
        try:
            from email.utils import parsedate_to_datetime
            received_at = parsedate_to_datetime(raw_date).isoformat()
        except Exception:
            received_at = None

    body = _body_text(msg).strip()

    _mailing_list_headers = ("List-ID", "List-Unsubscribe", "List-Post", "List-Archive", "List-Help",
                              "X-Mailchimp-ID", "X-Campaign")
    is_mailing_list = any(msg.get(h) for h in _mailing_list_headers)
    if not is_mailing_list:
        prec = (_header_str(msg, "Precedence") or "").strip().lower()
        is_mailing_list = prec in ("bulk", "list", "junk")

    return {
        "email_id": email_id,
        "message_id": message_id,
        "subject": subject,
        "sender": sender,
        "recipient": recipient,
        "cc": cc,
        "received_at": received_at,
        "body": body or "(no body)",
        "is_mailing_list": 1 if is_mailing_list else 0,
    }


# ---------------------------------------------------------------------------
# Email fetching
# ---------------------------------------------------------------------------

def fetch_emails(
    host: str,
    port: int,
    username: str,
    password: str,
    folder: str = "INBOX",
    limit: int = 500,
    since_uid: int = 0,
) -> tuple[list[dict], int]:
    """
    Fetch emails from IMAP server.

    Returns (email_dicts, max_uid) where max_uid is the highest UID seen
    so it can be stored and used as since_uid on the next call.
    """
    conn = _connect(host, port, username, password)
    try:
        conn.select(folder, readonly=True)

        if since_uid > 0:
            search_criterion = f"UID {since_uid + 1}:*"
            typ, uids_data = conn.uid("search", None, search_criterion)
        else:
            typ, uids_data = conn.uid("search", None, "ALL")

        if typ != "OK" or not uids_data or not uids_data[0]:
            return [], since_uid

        uid_list = uids_data[0].split()
        # Limit to most-recent N
        uid_list = uid_list[-limit:]

        emails: list[dict] = []
        max_uid = since_uid

        for uid_bytes in uid_list:
            try:
                uid_int = int(uid_bytes)
            except ValueError:
                continue
            max_uid = max(max_uid, uid_int)

            typ2, msg_data = conn.uid("fetch", uid_bytes, "(RFC822)")
            if typ2 != "OK" or not msg_data:
                continue
            for item in msg_data:
                if isinstance(item, tuple) and len(item) == 2:
                    parsed = _parse_raw_bytes(uid_bytes, item[1])
                    if parsed:
                        emails.append(parsed)
                    break

        return emails, max_uid
    finally:
        try:
            conn.logout()
        except Exception:
            pass
