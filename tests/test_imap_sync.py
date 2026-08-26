from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import imap_service


def _mock_conn(uid_search_line: bytes, fetch_ok: bool = True) -> MagicMock:
    conn = MagicMock()
    conn.uid.side_effect = lambda cmd, *args: (
        ("OK", [uid_search_line]) if cmd == "search" else _mock_fetch(fetch_ok)
    )
    conn.untagged_responses = {"UIDVALIDITY": [42]}
    return conn


def _mock_fetch(ok: bool) -> tuple[str, list]:
    if not ok:
        return ("NO", [])
    return (
        "OK",
        [(b"1", b"From: a@b.com\r\nSubject: Hi\r\n\r\nBody")],
    )


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
