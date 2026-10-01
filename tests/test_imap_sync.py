from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services import imap_service
from app.services.store import EmailStore


def _mock_fetch(ok: bool, uids: list[int] | None = None) -> tuple[str, list]:
    if not ok:
        return ("NO", [])
    uid = uids[0] if uids else 1
    meta = f"1 (UID {uid} BODY[] {{5}})".encode()
    return (
        "OK",
        [(meta, b"From: a@b.com\r\nSubject: Hi\r\n\r\nBody")],
    )


def _mock_conn(uid_search_line: bytes, fetch_ok: bool = True, fetch_uids: list[int] | None = None) -> MagicMock:
    conn = MagicMock()
    fetch_uids = fetch_uids or [1]

    def uid_handler(cmd, *args):
        if cmd == "search":
            return ("OK", [uid_search_line])
        uid_arg = args[0]
        if isinstance(uid_arg, bytes) and "," in uid_arg.decode():
            first_uid = int(uid_arg.decode().split(",")[0])
            return _mock_fetch(fetch_ok, [first_uid])
        if isinstance(uid_arg, bytes):
            try:
                return _mock_fetch(fetch_ok, [int(uid_arg.decode())])
            except ValueError:
                return _mock_fetch(fetch_ok, fetch_uids)
        return _mock_fetch(fetch_ok, fetch_uids)

    conn.uid.side_effect = uid_handler
    conn.untagged_responses = {"UIDVALIDITY": [42]}
    return conn


@patch("app.services.imap_service._connect")
def test_fetch_uid_batch_uses_single_multi_uid_fetch(mock_connect: MagicMock) -> None:
    conn = _mock_conn(b"101 102", fetch_uids=[101, 102])
    mock_connect.return_value = conn

    imap_service.fetch_emails(
        host="imap.test",
        port=993,
        username="u@test.com",
        password="pw",
        since_uid=100,
    )

    fetch_calls = [c for c in conn.uid.call_args_list if c.args and c.args[0] == "fetch"]
    assert fetch_calls
    uid_arg = fetch_calls[0].args[1]
    assert isinstance(uid_arg, bytes)
    assert "," in uid_arg.decode()


@patch("app.services.imap_service._connect")
def test_fetch_emails_uidvalidity_resets_checkpoint(mock_connect: MagicMock) -> None:
    conn = _mock_conn(b"101 102")
    mock_connect.return_value = conn

    emails, last_uid, backfill_uid, uidvalidity = imap_service.fetch_emails(
        host="imap.test",
        port=993,
        username="u@test.com",
        password="pw",
        since_uid=50,
        stored_uidvalidity=99,
    )

    search_calls = [c for c in conn.uid.call_args_list if c.args and c.args[0] == "search"]
    assert search_calls, "expected a UID search after UIDVALIDITY reset"
    assert any("ALL" in str(c) for c in search_calls)


def test_parse_fetch_items_reads_gmail_thrid() -> None:
    meta = b"1 (X-GM-THRID 1490737687333300257 UID 101 BODY[] {5})"
    payload = b"From: a@b.com\r\nSubject: Hi\r\n\r\nHello body"
    items = imap_service._parse_fetch_items([(meta, payload)])
    assert len(items) == 1
    uid, raw, thrid = items[0]
    assert uid == 101
    assert raw == payload
    assert thrid == format(1490737687333300257, "x")


@patch("app.services.imap_service._connect")
def test_fetch_emails_first_sync_sets_backfill(mock_connect: MagicMock) -> None:
    conn = _mock_conn(b"1 2 3 4 5")
    mock_connect.return_value = conn

    emails, last_uid, backfill_uid, uidvalidity = imap_service.fetch_emails(
        host="imap.test",
        port=993,
        username="u@test.com",
        password="pw",
        since_uid=0,
        backfill_uid=0,
        limit=2,
    )

    assert len(emails) <= 2
    assert last_uid >= 0


@patch("app.services.imap_service._connect")
def test_fetch_emails_failed_fetch_does_not_advance_uid(mock_connect: MagicMock) -> None:
    conn = MagicMock()
    conn.uid.side_effect = [
        ("OK", [b"100"]),
        ("NO", []),
    ]
    conn.untagged_responses = {"UIDVALIDITY": [1]}
    mock_connect.return_value = conn

    emails, last_uid, backfill_uid, uidvalidity = imap_service.fetch_emails(
        host="imap.test",
        port=993,
        username="u@test.com",
        password="pw",
        since_uid=99,
    )

    assert emails == []
    assert last_uid == 99


def test_imap_host_from_mx_google_workspace() -> None:
    assert imap_service.imap_host_from_mx(["aspmx.l.google.com", "aspmx2.googlemail.com"]) == "imap.gmail.com"


def test_imap_host_from_mx_microsoft_365() -> None:
    assert (
        imap_service.imap_host_from_mx(["yourorg.mail.protection.outlook.com"])
        == "outlook.office365.com"
    )


def test_imap_host_from_mx_unknown() -> None:
    assert imap_service.imap_host_from_mx(["mail.example.com"]) == ""


def test_guess_imap_host_known_gmail() -> None:
    assert imap_service.guess_imap_host("me@gmail.com") == "imap.gmail.com"


@patch("app.services.imap_service.lookup_mx", return_value=["aspmx.l.google.com"])
def test_guess_imap_host_google_workspace(mock_mx: MagicMock) -> None:
    assert imap_service.guess_imap_host("me@ghcdsstudent.org") == "imap.gmail.com"
    mock_mx.assert_called_once_with("ghcdsstudent.org")


@patch("app.services.imap_service.host_resolves")
@patch("app.services.imap_service.guess_imap_host", return_value="imap.gmail.com")
def test_resolve_imap_host_replaces_unresolved_guess(
    mock_guess: MagicMock, mock_resolves: MagicMock
) -> None:
    mock_resolves.side_effect = lambda host: host == "imap.gmail.com"
    assert (
        imap_service.resolve_imap_host("me@ghcdsstudent.org", "imap.ghcdsstudent.org")
        == "imap.gmail.com"
    )


def _raw_message(uid: str) -> dict:
    return {
        "email_id": f"uid-{uid}",
        "message_id": f"<{uid}@example>",
        "subject": f"Message {uid}",
        "sender": "a@b.com",
        "recipient": "me@example.com",
        "cc": "",
        "body": "Hello",
        "received_at": "2026-09-01T00:00:00+00:00",
        "in_reply_to": "",
        "is_mailing_list": 0,
    }


@patch("app.routes._imap_password_for_account", return_value=("pw", None))
@patch("app.routes.imap_service.fetch_emails")
def test_sync_pages_until_backfill_exhausted(mock_fetch: MagicMock, _password: MagicMock) -> None:
    from app.routes import sync_one_account

    pages = {"n": 0}

    def fake_fetch(**kwargs: object) -> tuple:
        pages["n"] += 1
        if pages["n"] == 1:
            assert kwargs["since_uid"] == 0
            assert kwargs["backfill_uid"] == 0
            assert kwargs["limit"] == 2
            return ([_raw_message("1")], 5, 3, 9)
        if pages["n"] == 2:
            assert kwargs["since_uid"] == 5
            assert kwargs["backfill_uid"] == 3
            return ([_raw_message("2")], 5, 0, 9)
        raise AssertionError("sync kept fetching after the backfill cursor was exhausted")

    mock_fetch.side_effect = fake_fetch
    with tempfile.TemporaryDirectory() as tmp:
        store = EmailStore(Path(tmp) / "sync.db")
        store.initialize()
        user = "me@example.com"
        account_id = store.save_imap_account(user, "acct@example.com", "imap.example.com", 993, "cipher")
        store.update_imap_sync_prefs(account_id, "", 2)
        account = store.get_imap_account(account_id, user)
        assert account is not None
        imported, err = sync_one_account(store, account, user, MagicMock(), limit=2)
        assert err is None
        assert imported == 2
        assert pages["n"] == 2
        folder = store.get_folder_sync(account_id, "INBOX")
        assert folder is not None
        assert folder["backfill_uid"] == 0
        assert len(store.list_emails(user_email=user, limit=10)) == 2


@patch("app.services.imap_service.host_resolves", return_value=True)
def test_resolve_imap_host_keeps_resolvable_override(mock_resolves: MagicMock) -> None:
    assert imap_service.resolve_imap_host("me@gmail.com", "mail.custom.example") == "mail.custom.example"
