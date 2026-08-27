from __future__ import annotations

from unittest.mock import patch

from app import create_app
from app.services import mail


def _smtp_app(**overrides):
    app = create_app()
    config = {
        "TESTING": True,
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": 587,
        "SMTP_USERNAME": "user@example.com",
        "SMTP_PASSWORD": "secret",
        "SMTP_FROM": "noreply@example.com",
        "SMTP_USE_TLS": True,
    }
    config.update(overrides)
    app.config.update(config)
    return app


def test_send_email_starttls() -> None:
    app = _smtp_app()
    with app.app_context():
        with patch("app.services.mail.smtplib.SMTP") as mock_smtp:
            client = mock_smtp.return_value.__enter__.return_value
            ok, err = mail.send_email(
                "to@example.com",
                "Your Inbox Tools verification code",
                "Your verification code is: 123456",
            )
            assert ok
            assert err == ""
            client.starttls.assert_called_once()
            client.login.assert_called_once_with("user@example.com", "secret")
            client.send_message.assert_called_once()


def test_send_email_requires_host() -> None:
    app = _smtp_app(SMTP_HOST="")
    with app.app_context():
        ok, err = mail.send_email("to@example.com", "s", "b")
        assert not ok
        assert "not configured" in err.lower()


def test_send_email_smtps() -> None:
    app = _smtp_app(SMTP_USE_TLS=False, SMTP_PORT=465)
    with app.app_context():
        with patch("app.services.mail.smtplib.SMTP_SSL") as mock_ssl:
            client = mock_ssl.return_value.__enter__.return_value
            ok, err = mail.send_email("to@example.com", "s", "b")
            assert ok
            assert err == ""
            client.login.assert_called_once()
            client.send_message.assert_called_once()
