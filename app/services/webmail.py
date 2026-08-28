"""Build webmail URLs for opening originals and composing replies in the user's browser."""
from __future__ import annotations

from urllib.parse import quote

GMAIL_HOSTS = frozenset({"imap.gmail.com", "imap.googlemail.com"})
OUTLOOK_HOSTS = frozenset(
    {
        "outlook.office365.com",
        "imap-mail.outlook.com",
        "imap.outlook.com",
    }
)


def provider_for_imap_host(imap_host: str) -> str:
    host = (imap_host or "").strip().lower()
    if host in GMAIL_HOSTS:
        return "gmail"
    if host in OUTLOOK_HOSTS:
        return "outlook"
    return "mailto"


def resolve_provider(imap_host: str, user_pref: str = "auto") -> str:
    pref = (user_pref or "auto").strip().lower()
    if pref in ("gmail", "outlook", "mailto"):
        return pref
    return provider_for_imap_host(imap_host)


def normalize_message_id(message_id: str) -> str:
    mid = (message_id or "").strip()
    if mid.startswith("<") and mid.endswith(">"):
        mid = mid[1:-1]
    return mid


def open_message_url(
    *,
    provider: str,
    account_email: str,
    message_id: str,
    subject: str = "",
    gmail_thrid: str = "",
) -> str | None:
    prov = (provider or "auto").lower()
    if prov == "gmail":
        auth = quote(account_email) if account_email else ""
        auth_q = f"authuser={auth}&" if auth else ""
        hex_id = (gmail_thrid or "").strip().lower()
        if hex_id and all(c in "0123456789abcdef" for c in hex_id):
            return f"https://mail.google.com/mail/?{auth_q}#all/{hex_id}"
        mid = normalize_message_id(message_id)
        if not mid:
            return None
        return (
            f"https://mail.google.com/mail/?{auth_q}"
            f"#search/rfc822msgid%3A{quote(mid, safe='')}"
        )
    if prov == "outlook":
        q = quote(subject or normalize_message_id(message_id))
        return f"https://outlook.office.com/mail/search/id/{q}"
    return None


def compose_url(
    *,
    provider: str,
    account_email: str,
    to_addr: str,
    subject: str,
    body: str,
) -> str | None:
    prov = (provider or "auto").lower()
    if prov == "gmail":
        auth = quote(account_email) if account_email else ""
        auth_q = f"&authuser={auth}" if auth else ""
        return (
            "https://mail.google.com/mail/?view=cm&fs=1"
            f"&to={quote(to_addr)}"
            f"&su={quote(subject)}"
            f"&body={quote(body)}"
            f"{auth_q}"
        )
    if prov == "outlook":
        return (
            "https://outlook.office.com/mail/deeplink/compose"
            f"?to={quote(to_addr)}"
            f"&subject={quote(subject)}"
            f"&body={quote(body)}"
        )
    return None


def mailto_url(to_addr: str, subject: str, body: str) -> str:
    return f"mailto:{quote(to_addr)}?subject={quote(subject)}&body={quote(body)}"


def compose_links(
    *,
    provider: str,
    account_email: str,
    to_addr: str,
    subject: str,
    body: str,
) -> dict[str, str | None]:
    """Return primary https compose URL and optional mailto fallback."""
    https = compose_url(
        provider=provider,
        account_email=account_email,
        to_addr=to_addr,
        subject=subject,
        body=body,
    )
    mailto = mailto_url(to_addr, subject, body)
    if provider == "mailto" or not https:
        return {"primary": mailto, "secondary": None, "label": "Open in mail app"}
    return {
        "primary": https,
        "secondary": mailto,
        "label": "Open in Gmail" if provider == "gmail" else "Open in Outlook",
    }
