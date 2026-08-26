from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from app import create_app
from app.services import crypto
from app.services.store import EmailStore


def test_login_email_only_rejected() -> None:
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.test_client() as client:
        response = client.post("/login", data={"email": "nobody@example.com"})
        assert response.status_code == 200
        with client.session_transaction() as sess:
            assert sess.get("user_email") != "nobody@example.com"


def test_login_unknown_email_prompts_signup() -> None:
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.test_client() as client:
        response = client.post(
            "/login",
            data={"email": "new-user@example.com", "app_password": "secret12"},
        )
        assert response.status_code == 200
        assert b"No account found" in response.data
        with client.session_transaction() as sess:
            assert sess.get("user_email") != "new-user@example.com"


def test_api_senders_requires_auth() -> None:
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        response = client.get("/api/senders")
        assert response.status_code == 401


def test_set_app_password_allows_login() -> None:
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    store: EmailStore = app.extensions["email_store"]
    email = "pytest-user@example.com"
    from werkzeug.security import generate_password_hash

    store.set_app_password(email, generate_password_hash("secret12", method="pbkdf2:sha256"))

    with app.test_client() as client:
        response = client.post(
            "/login",
            data={"email": email, "app_password": "secret12"},
        )
        assert response.status_code == 302
        with client.session_transaction() as sess:
            assert sess.get("user_email") == email


def test_login_imap_recovery_required() -> None:
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    store: EmailStore = app.extensions["email_store"]
    email = "imap-user@example.com"
    store.set_app_password(email, "")
    encrypted = crypto.encrypt(
        "secret-app-pw",
        app.config["CREDENTIAL_ENCRYPTION_KEY"],
        purpose="imap",
    )
    store.save_imap_account(
        user_email=email,
        account_email=email,
        imap_host="imap.example.com",
        imap_port=993,
        encrypted_password=encrypted,
    )

    with app.test_client() as client:
        response = client.post("/login", data={"email": email})
        assert response.status_code == 200
        assert b"Mailbox App Password" in response.data

        response = client.post(
            "/login",
            data={"email": email, "app_password": "hacker12"},
        )
        assert response.status_code == 200
        with client.session_transaction() as sess:
            assert sess.get("user_email") != email


@patch("app.routes.imap_service.test_connection", return_value=(True, ""))
def test_login_imap_recovery_success(mock_test: MagicMock) -> None:
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    store: EmailStore = app.extensions["email_store"]
    email = "imap-ok@example.com"
    store.set_app_password(email, "")
    encrypted = crypto.encrypt(
        "app-pw",
        app.config["CREDENTIAL_ENCRYPTION_KEY"],
        purpose="imap",
    )
    store.save_imap_account(
        user_email=email,
        account_email=email,
        imap_host="imap.example.com",
        imap_port=993,
        encrypted_password=encrypted,
    )

    with app.test_client() as client:
        response = client.post(
            "/login",
            data={"email": email, "imap_password": "app-pw"},
        )
        assert response.status_code == 302
        with client.session_transaction() as sess:
            assert sess.get("user_email") == email
    mock_test.assert_called()


def test_signup_without_code_does_not_create_account() -> None:
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    store: EmailStore = app.extensions["email_store"]
    email = "signup-blocked@example.com"

    with app.test_client() as client:
        response = client.post(
            "/signup",
            data={
                "action": "confirm",
                "email": email,
                "verification_code": "000000",
                "new_app_password": "secret12",
                "confirm_app_password": "secret12",
            },
        )
        assert response.status_code == 200
        assert not store.get_app_password_hash(email)


@patch("app.routes._send_signup_code", return_value=(True, "", True))
@patch("app.routes._generate_verification_code", return_value="482193")
def test_signup_with_correct_code_creates_account(mock_code: MagicMock, mock_send: MagicMock) -> None:
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    store: EmailStore = app.extensions["email_store"]
    email = f"signup-ok-{uuid.uuid4().hex[:8]}@example.com"
    code = "482193"

    with app.test_client() as client:
        response = client.post(
            "/signup",
            data={"action": "send_code", "email": email},
        )
        assert response.status_code == 200
        assert b"verification code" in response.data.lower()

        response = client.post(
            "/signup",
            data={
                "action": "confirm",
                "email": email,
                "verification_code": code,
                "new_app_password": "secret12",
                "confirm_app_password": "secret12",
            },
        )
        assert response.status_code == 302
        assert store.get_app_password_hash(email)
        with client.session_transaction() as sess:
            assert sess.get("user_email") == email
    mock_send.assert_called()


@patch("app.routes._send_signup_code", return_value=(True, "", True))
@patch("app.routes._generate_verification_code", return_value="482193")
def test_signup_wrong_code_rejected(mock_code: MagicMock, mock_send: MagicMock) -> None:
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    store: EmailStore = app.extensions["email_store"]
    email = f"signup-wrong-{uuid.uuid4().hex[:8]}@example.com"

    with app.test_client() as client:
        client.post("/signup", data={"action": "send_code", "email": email})
        response = client.post(
            "/signup",
            data={
                "action": "confirm",
                "email": email,
                "verification_code": "999999",
                "new_app_password": "secret12",
                "confirm_app_password": "secret12",
            },
        )
        assert response.status_code == 200
        assert not store.get_app_password_hash(email)


def test_help_page_public() -> None:
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        response = client.get("/help")
        assert response.status_code == 200
        assert b"App Password" in response.data


def test_guess_imap_port_proton() -> None:
    from app.routes import _guess_imap_port

    assert _guess_imap_port("me@proton.me", "127.0.0.1") == 1143
    assert _guess_imap_port("me@gmail.com", "imap.gmail.com") == 993


def test_help_page_mentions_workspace_imap_host() -> None:
    app = create_app()
    app.config.update(TESTING=True)
    with app.test_client() as client:
        response = client.get("/help")
        assert response.status_code == 200
        assert b"imap.gmail.com" in response.data
        assert b"imap.yourschool.org" in response.data


@patch("app.routes.sync_one_account", return_value=(0, ""))
@patch("app.routes.imap_service.test_connection", return_value=(True, ""))
@patch("app.services.imap_service.host_resolves")
@patch("app.services.imap_service.lookup_mx", return_value=["aspmx.l.google.com"])
def test_accounts_add_rewrites_unresolved_workspace_host(
    mock_mx: MagicMock,
    mock_resolves: MagicMock,
    mock_test: MagicMock,
    mock_sync: MagicMock,
) -> None:
    mock_resolves.side_effect = lambda host: host == "imap.gmail.com"
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    store: EmailStore = app.extensions["email_store"]
    email = f"workspace-{uuid.uuid4().hex[:8]}@ghcdsstudent.org"
    from werkzeug.security import generate_password_hash

    store.set_app_password(email, generate_password_hash("secret12", method="pbkdf2:sha256"))

    with app.test_client() as client:
        client.post("/login", data={"email": email, "app_password": "secret12"})
        response = client.post(
            "/accounts/add",
            data={
                "account_email": email,
                "password": "xxxx xxxx xxxx xxxx",
                "imap_host": "imap.ghcdsstudent.org",
                "imap_port": "993",
            },
        )
        assert response.status_code == 302

    accounts = store.list_imap_accounts(email)
    assert len(accounts) == 1
    assert accounts[0]["imap_host"] == "imap.gmail.com"
    mock_test.assert_called()
    assert mock_test.call_args.args[0] == "imap.gmail.com"
