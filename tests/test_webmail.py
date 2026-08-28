"""Tests for webmail URL builders."""
from __future__ import annotations

from app.services import webmail


def test_gmail_compose_url() -> None:
    url = webmail.compose_url(
        provider="gmail",
        account_email="me@gmail.com",
        to_addr="teacher@school.org",
        subject="Re: Homework",
        body="Hello",
    )
    assert url is not None
    assert url.startswith("https://mail.google.com/mail/")
    assert "view=cm" in url
    assert "authuser=me%40gmail.com" in url


def test_gmail_open_message_rfc822() -> None:
    url = webmail.open_message_url(
        provider="gmail",
        account_email="me@gmail.com",
        message_id="<abc@mail.gmail.com>",
    )
    assert url is not None
    assert "rfc822msgid" in url


def test_gmail_open_uses_thread_id_when_present() -> None:
    url = webmail.open_message_url(
        provider="gmail",
        account_email="me@gmail.com",
        message_id="<abc@mail.gmail.com>",
        gmail_thrid="14a73b9c2d1e",
    )
    assert url is not None
    assert "#all/14a73b9c2d1e" in url
    assert "rfc822msgid" not in url


def test_resolve_provider_auto() -> None:
    assert webmail.resolve_provider("imap.gmail.com", "auto") == "gmail"
    assert webmail.resolve_provider("outlook.office365.com", "auto") == "outlook"
