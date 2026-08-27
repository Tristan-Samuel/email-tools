from __future__ import annotations

from email.message import EmailMessage

from app import create_app
from app.services.email_parser import (
    extract_body,
    html_to_text,
    is_url_heavy_plaintext,
    normalize_body_text,
)


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


def test_is_url_heavy_plaintext() -> None:
    heavy = "Visit <https://a.com> Apply <https://b.com> See <https://c.com> More <https://d.com>"
    assert is_url_heavy_plaintext(heavy)
    assert not is_url_heavy_plaintext("Please reply about your homework by Friday.")


def test_format_email_body_linkifies_label_url() -> None:
    app = create_app()
    with app.app_context():
        rendered = app.jinja_env.filters["format_email_body"](
            "Visit <https://example.com/visit> and read more."
        )
    assert "Visit" in rendered
    assert "example.com/visit" in rendered
    assert "<https://" not in rendered
