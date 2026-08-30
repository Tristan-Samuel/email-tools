from __future__ import annotations

from app import create_app


def test_signup_rejects_email_outside_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("SIGNUP_ALLOWED_EMAIL", "owner@example.com")
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.test_client() as client:
        response = client.post(
            "/signup",
            data={"action": "send_code", "email": "other@example.com"},
        )
        assert response.status_code == 200
        assert b"not allowed" in response.data


def test_signup_rejects_wrong_invite_token(monkeypatch) -> None:
    monkeypatch.setenv("SIGNUP_INVITE_TOKEN", "correct-token")
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.test_client() as client:
        response = client.post(
            "/signup",
            data={
                "action": "send_code",
                "email": "anyone@example.com",
                "invite_token": "wrong",
            },
        )
        assert response.status_code == 200
        assert b"Invalid invite token" in response.data


def test_health_unauthenticated() -> None:
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.get_json() == {"ok": True}
