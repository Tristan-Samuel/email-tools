from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import imap_service


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


@patch("app.services.imap_service.host_resolves", return_value=True)
def test_resolve_imap_host_keeps_resolvable_override(mock_resolves: MagicMock) -> None:
    assert imap_service.resolve_imap_host("me@gmail.com", "mail.custom.example") == "mail.custom.example"
