from __future__ import annotations

from email.message import EmailMessage

from app import create_app
from app.services.email_parser import (
    expand_inline_breaks,
    extract_body,
    extract_body_parts,
    html_to_text,
    is_url_heavy_plaintext,
    normalize_body_text,
)
from app.services.html_sanitize import sanitize_email_html


def test_html_to_text_preserves_link_labels() -> None:
    html = "<p>Visit <a href='https://example.com/visit?utm=1'>our campus</a></p>"
    text = html_to_text(html)
    assert "our campus" in text
    assert "https://" not in text


def test_extract_body_prefers_html_when_plain_is_url_heavy() -> None:
    msg = EmailMessage()
    msg["From"] = "admissions@school.edu"
    msg["Subject"] = "Apply today"
    msg.set_content(
        "Visit <https://school.edu/visit?utm_campaign=sp> "
        "Apply <https://school.edu/apply?utm_campaign=sp> "
        "Academics <https://school.edu/academics?utm_campaign=sp> "
        "Admissions <https://school.edu/admissions?utm_campaign=sp>"
    )
    msg.add_alternative(
        "<html><body><p>Visit our campus and apply for fall admission.</p></body></html>",
        subtype="html",
    )
    body = extract_body(msg)
    assert "fall admission" in body.lower()
    assert "utm_campaign" not in body


def test_normalize_body_text_preserves_paragraphs() -> None:
    text = normalize_body_text("Line one\n\nLine two")
    assert text == "Line one\n\nLine two"


def test_normalize_body_text_preserves_single_line_breaks() -> None:
    text = normalize_body_text("Line one\nLine two")
    assert text == "Line one\nLine two"


def test_expand_inline_breaks_for_forwarded_mail() -> None:
    blob = (
        "Sent from my iPhone Begin forwarded message: "
        "From: Amy Bowler <amy@example.com> Date: August 3, 2026 Subject: Internship"
    )
    expanded = expand_inline_breaks(blob)
    assert "Begin forwarded message:" in expanded
    assert "\nFrom:" in expanded
    assert "\nSubject:" in expanded


def test_is_url_heavy_plaintext() -> None:
    heavy = "Visit <https://a.com> Apply <https://b.com> See <https://c.com> More <https://d.com>"
    assert is_url_heavy_plaintext(heavy)
    assert not is_url_heavy_plaintext("Please reply about your homework by Friday.")


def test_extract_body_parts_returns_sanitized_html() -> None:
    msg = EmailMessage()
    msg["From"] = "dean@ghcds.org"
    msg["Subject"] = "Grade follow-up"
    msg.add_alternative(
        "<html><body><p>Good afternoon</p><script>alert(1)</script></body></html>",
        subtype="html",
    )
    plain, body_html = extract_body_parts(msg)
    assert "Good afternoon" in plain
    assert body_html
    assert "<script" not in body_html.lower()
    assert "Good afternoon" in body_html


def test_sanitize_email_html_defers_remote_images() -> None:
    raw = '<p>Hi</p><img src="https://cdn.example.com/logo.png" alt="Logo">'
    cleaned = sanitize_email_html(raw)
    assert "cdn.example.com" in cleaned
    assert 'data-src="https://cdn.example.com/logo.png"' in cleaned
    assert "<img" not in cleaned


def test_format_email_body_linkifies_short_label_only() -> None:
    app = create_app()
    with app.app_context():
        rendered = app.jinja_env.filters["format_email_body"](
            "Good afternoon Dean. Visit <https://example.com/visit> for details."
        )
    assert "Good afternoon Dean." in rendered
    assert "example.com/visit" in rendered
    assert rendered.count("<a ") == 1


def test_format_email_body_image_chip() -> None:
    app = create_app()
    with app.app_context():
        rendered = app.jinja_env.filters["format_email_body"](
            "Hello [image: back to school] there."
        )
    assert "email-img-placeholder" in rendered
    assert "back to school" in rendered
