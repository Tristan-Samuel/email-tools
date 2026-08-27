"""
IMAP email fetching service.

Works with any IMAP-over-SSL server — Gmail, Outlook, Yahoo, etc.
For Gmail use host=imap.gmail.com, port=993 and an App Password.
Google Workspace / Microsoft 365 custom domains are detected from MX records.

Returns email dicts in the same format as email_parser.py so they
can be passed directly to summary.build_email_record().
"""
from __future__ import annotations

import imaplib
import logging
import re
import socket
import ssl
import struct
from collections.abc import Callable
from datetime import date
from email.parser import BytesParser
from email import policy

from .email_parser import message_email_id, parse_message


GMAIL_HOST = "imap.gmail.com"
GMAIL_PORT = 993

KNOWN_IMAP_HOSTS: dict[str, str] = {
    "gmail.com": "imap.gmail.com",
    "googlemail.com": "imap.gmail.com",
    "yahoo.com": "imap.mail.yahoo.com",
    "yahoo.co.uk": "imap.mail.yahoo.com",
    "outlook.com": "outlook.office365.com",
    "hotmail.com": "outlook.office365.com",
    "live.com": "outlook.office365.com",
    "icloud.com": "imap.mail.me.com",
    "me.com": "imap.mail.me.com",
    "mac.com": "imap.mail.me.com",
    "protonmail.com": "127.0.0.1",
    "proton.me": "127.0.0.1",
}

# ponytail: suffix match on MX exchange, not full autodiscover/SRV.
_MX_IMAP_SUFFIXES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("google.com", "googlemail.com", "gmail.com"), "imap.gmail.com"),
    (("outlook.com", "protection.outlook.com", "microsoft.com"), "outlook.office365.com"),
    (("yahoodns.net", "yahoo.com"), "imap.mail.yahoo.com"),
)

_DNS_SERVERS = ("8.8.8.8", "1.1.1.1")
_PARSER = BytesParser(policy=policy.default)
_FOLDER_LINE_RE = re.compile(r'"([^"]+)"\s*$')

SENT_FOLDER_MARKERS = (
    "sent",
    "sent items",
    "sent messages",
    "[gmail]/sent mail",
    "inbox.sent",
)


def is_sent_folder(folder: str) -> bool:
    """Return True when folder name looks like the provider's Sent mailbox."""
    normalized = (folder or "").strip().lower()
    if not normalized:
        return False
    if normalized in ("sent", "sent items", "sent messages"):
        return True
    return any(marker in normalized for marker in SENT_FOLDER_MARKERS if marker not in ("sent",))


def default_enabled_folders(folders: list[str]) -> set[str]:
    """INBOX plus Sent-like folders enabled on first connect."""
    enabled = {"INBOX"}
    for folder in folders:
        if is_sent_folder(folder):
            enabled.add(folder)
    return enabled
UID_META_RE = re.compile(rb"UID (\d+)")
FETCH_CHUNK_SIZE = 25
logger = logging.getLogger(__name__)

ProgressFn = Callable[[int, int], None]


def host_resolves(host: str) -> bool:
    """Return True if *host* has a DNS A/AAAA record."""
    if not host:
        return False
    try:
        socket.getaddrinfo(host, None)
        return True
    except OSError:
        return False


def imap_host_from_mx(exchanges: list[str]) -> str:
    """Map MX exchange hostnames to a known IMAP server, or empty string."""
    for exchange in exchanges:
        name = exchange.rstrip(".").lower()
        for suffixes, imap_host in _MX_IMAP_SUFFIXES:
            if any(name == suffix or name.endswith("." + suffix) for suffix in suffixes):
                return imap_host
    return ""


def _dns_name_at(packet: bytes, offset: int) -> tuple[str, int]:
    labels: list[str] = []
    jumped = False
    end = offset
    for _ in range(20):
        if offset >= len(packet):
            break
        length = packet[offset]
        if length == 0:
            if not jumped:
                end = offset + 1
            break
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(packet):
                break
            ptr = ((length & 0x3F) << 8) | packet[offset + 1]
            if not jumped:
                end = offset + 2
                jumped = True
            offset = ptr
            continue
        offset += 1
        if offset + length > len(packet):
            break
        labels.append(packet[offset:offset + length].decode("ascii", "ignore"))
        offset += length
        if not jumped:
            end = offset
    return ".".join(labels).rstrip(".").lower(), end


def _parse_mx_answers(packet: bytes) -> list[str]:
    if len(packet) < 12:
        return []
    ancount = struct.unpack("!H", packet[6:8])[0]
    offset = 12
    _, offset = _dns_name_at(packet, offset)
    offset += 4
    exchanges: list[str] = []
    for _ in range(ancount):
        if offset + 10 > len(packet):
            break
        _, offset = _dns_name_at(packet, offset)
        rtype, _rclass, _ttl, rdlength = struct.unpack("!HHIH", packet[offset:offset + 10])
        offset += 10
        if rtype == 15 and rdlength >= 3 and offset + rdlength <= len(packet):
            exch, _ = _dns_name_at(packet, offset + 2)
            if exch:
                exchanges.append(exch)
        offset += rdlength
    return exchanges


def lookup_mx(domain: str, timeout: float = 1.5) -> list[str]:
    """Return MX exchange hostnames for *domain*. Empty on timeout or parse failure."""
    labels = domain.strip(".").lower().split(".")
    if not domain or any(not label or len(label) > 63 for label in labels):
        return []
    try:
        qname = b"".join(bytes([len(p)]) + p.encode("ascii") for p in labels) + b"\x00"
    except UnicodeEncodeError:
        return []
    query = struct.pack("!HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0) + qname + struct.pack("!HH", 15, 1)
    for server in _DNS_SERVERS:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(timeout)
            sock.sendto(query, (server, 53))
            packet, _ = sock.recvfrom(4096)
        except OSError:
            continue
        finally:
            sock.close()
        answers = _parse_mx_answers(packet)
        if answers:
            return answers
    return []


def guess_imap_host(email: str) -> str:
    """Return the IMAP hostname for an address (known domain, MX provider, or imap.{domain})."""
    domain = email.split("@")[-1].lower() if "@" in email else ""
    if not domain:
        return ""
    if domain in KNOWN_IMAP_HOSTS:
        return KNOWN_IMAP_HOSTS[domain]
    mx_host = imap_host_from_mx(lookup_mx(domain))
    if mx_host:
        return mx_host
    return f"imap.{domain}"


def guess_imap_port(email: str, host: str) -> int:
    domain = email.split("@")[-1].lower() if "@" in email else ""
    if host == "127.0.0.1" or domain in ("protonmail.com", "proton.me"):
        return 1143
    return 993


def resolve_imap_host(email: str, provided_host: str) -> str:
    """Prefer a resolvable user-supplied host; otherwise the MX/domain guess."""
    provided = provided_host.strip()
    guessed = guess_imap_host(email)
    if not provided:
        return guessed
    if host_resolves(provided):
        return provided
    if guessed and guessed != provided and host_resolves(guessed):
        return guessed
    return provided


def _connect(host: str, port: int, username: str, password: str) -> imaplib.IMAP4_SSL:
    ctx = ssl.create_default_context()
    try:
        conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
    except socket.gaierror:
        fallback = guess_imap_host(username)
        if not fallback or fallback == host:
            raise
        logger.info("IMAP host %s did not resolve; trying %s", host, fallback)
        conn = imaplib.IMAP4_SSL(fallback, port, ssl_context=ctx)
    conn.login(username, password)
    return conn


def test_connection(host: str, port: int, username: str, password: str) -> tuple[bool, str]:
    """Return (ok, error_message)."""
    try:
        conn = _connect(host, port, username, password)
        conn.logout()
        return True, ""
    except imaplib.IMAP4.error as exc:
        return False, str(exc)
    except socket.gaierror as exc:
        return False, (
            f"{exc}. School and work Google accounts usually use imap.gmail.com; "
            "Microsoft 365 uses outlook.office365.com."
        )
    except OSError as exc:
        return False, str(exc)


def _uidvalidity(conn: imaplib.IMAP4_SSL) -> int:
    responses = getattr(conn, "untagged_responses", {})
    raw = responses.get("UIDVALIDITY", [None])[0]
    try:
        return int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        return 0


def _parse_uid_list(uids_data: list[bytes] | None) -> list[int]:
    if not uids_data or not uids_data[0]:
        return []
    result: list[int] = []
    for uid_bytes in uids_data[0].split():
        try:
            result.append(int(uid_bytes))
        except ValueError:
            continue
    return result


def _parse_raw_bytes(uid_bytes: bytes, raw_bytes: bytes) -> dict | None:
    """Parse raw RFC 2822 bytes into an email dict."""
    try:
        msg = _PARSER.parsebytes(raw_bytes)
    except Exception:
        return None

    parsed = parse_message(msg)
    uid_hex = uid_bytes.decode() if isinstance(uid_bytes, bytes) else str(uid_bytes)
    if not parsed.get("message_id"):
        parsed["message_id"] = uid_hex
    parsed["email_id"] = message_email_id(msg, parsed["body"], fallback=uid_hex)
    return parsed


def _parse_fetch_items(msg_data: list | None) -> list[tuple[int, bytes]]:
    """Extract (uid, raw_bytes) pairs from a multi-message UID FETCH response."""
    results: list[tuple[int, bytes]] = []
    if not msg_data:
        return results
    for item in msg_data:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        meta, payload = item
        if not isinstance(payload, bytes) or len(payload) < 10:
            continue
        meta_b = meta if isinstance(meta, bytes) else str(meta).encode("ascii", "replace")
        match = UID_META_RE.search(meta_b)
        if not match:
            continue
        try:
            uid_int = int(match.group(1))
        except ValueError:
            continue
        results.append((uid_int, payload))
    return results


def _fetch_uid_batch(
    conn: imaplib.IMAP4_SSL,
    uid_ints: list[int],
    last_uid: int,
    on_progress: ProgressFn | None = None,
) -> tuple[list[dict], int, list[int]]:
    """Fetch UIDs in batched BODY.PEEK[] requests; bump last_uid only on successful parses."""
    emails: list[dict] = []
    parsed_uids: list[int] = []
    total = len(uid_ints)
    if on_progress:
        on_progress(0, total)
    for start in range(0, total, FETCH_CHUNK_SIZE):
        chunk_uids = uid_ints[start : start + FETCH_CHUNK_SIZE]
        uid_set = ",".join(str(uid_int) for uid_int in chunk_uids)
        typ2, msg_data = conn.uid("fetch", uid_set.encode(), "(BODY.PEEK[])")
        if typ2 != "OK" or not msg_data:
            if on_progress:
                on_progress(min(start + len(chunk_uids), total), total)
            continue
        for uid_int, raw_bytes in _parse_fetch_items(msg_data):
            uid_bytes = str(uid_int).encode()
            parsed = _parse_raw_bytes(uid_bytes, raw_bytes)
            if parsed:
                emails.append(parsed)
                parsed_uids.append(uid_int)
                last_uid = max(last_uid, uid_int)
        if on_progress:
            on_progress(min(start + len(chunk_uids), total), total)
    return emails, last_uid, parsed_uids


def list_folders(host: str, port: int, username: str, password: str) -> list[str]:
    """Return selectable IMAP folder names (skips \\Noselect)."""
    conn = _connect(host, port, username, password)
    folders: list[str] = []
    try:
        typ, data = conn.list()
        if typ != "OK" or not data:
            return ["INBOX"]
        for item in data:
            if not isinstance(item, bytes):
                continue
            line = item.decode(errors="replace")
            if "Noselect" in line or "NoSelect" in line:
                continue
            match = _FOLDER_LINE_RE.search(line)
            if match:
                folders.append(match.group(1))
        return folders if folders else ["INBOX"]
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _uids_for_search(conn: imaplib.IMAP4_SSL, criteria: str) -> list[int]:
    typ, uids_data = conn.uid("search", None, criteria)
    return _parse_uid_list(uids_data)


def fetch_emails(
    host: str,
    port: int,
    username: str,
    password: str,
    folder: str = "INBOX",
    limit: int = 500,
    since_uid: int = 0,
    backfill_uid: int = 0,
    stored_uidvalidity: int = 0,
    since_date: date | None = None,
    backfill_only: bool = False,
    on_progress: ProgressFn | None = None,
) -> tuple[list[dict], int, int, int]:
    """
    Fetch emails from IMAP server.

    Returns (email_dicts, last_uid, backfill_uid, uidvalidity).
    last_uid advances only for successfully parsed messages.
    """
    conn = _connect(host, port, username, password)
    try:
        conn.select(folder, readonly=True)
        uidvalidity = _uidvalidity(conn)

        if stored_uidvalidity and stored_uidvalidity != uidvalidity:
            since_uid = 0
            backfill_uid = 0

        last_uid = since_uid
        emails: list[dict] = []
        date_uids: set[int] | None = None
        if since_date is not None:
            since_str = since_date.strftime("%d-%b-%Y")
            date_uids = set(_uids_for_search(conn, f"SINCE {since_str}"))

        def _filter_uids(uid_list: list[int]) -> list[int]:
            if date_uids is None:
                return uid_list
            return [u for u in uid_list if u in date_uids]

        def _fetch_with_progress(uid_list: list[int]) -> tuple[list[dict], int, list[int]]:
            if not uid_list:
                if on_progress:
                    on_progress(1, 1)
                return [], last_uid, []
            return _fetch_uid_batch(conn, uid_list, last_uid, on_progress=on_progress)

        if not backfill_only and since_uid > 0:
            new_uids = _filter_uids(_uids_for_search(conn, f"UID {since_uid + 1}:*"))
            batch, last_uid, parsed = _fetch_with_progress(new_uids)
            emails.extend(batch)

        if backfill_uid > 0:
            old_uids = _filter_uids(_uids_for_search(conn, f"UID 1:{backfill_uid}"))
            if old_uids:
                chunk = old_uids[-limit:]
                batch, last_uid, parsed = _fetch_with_progress(chunk)
                emails.extend(batch)
                if parsed:
                    backfill_uid = min(parsed) - 1
                else:
                    backfill_uid = max(0, min(chunk) - 1)

        if not backfill_only and since_uid == 0 and backfill_uid == 0 and not emails:
            if date_uids is not None:
                all_uids = sorted(date_uids)
            else:
                all_uids = _uids_for_search(conn, "ALL")
            if not all_uids:
                return [], since_uid, 0, uidvalidity

            initial_uids = all_uids[-limit:]
            batch, last_uid, parsed = _fetch_with_progress(initial_uids)
            emails.extend(batch)
            if parsed:
                min_parsed = min(parsed)
                if min_parsed > 1:
                    backfill_uid = min_parsed - 1
                else:
                    backfill_uid = 0
            elif initial_uids:
                backfill_uid = max(0, min(initial_uids) - 1)

        return emails, last_uid, backfill_uid, uidvalidity
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def fetch_recent_emails(
    host: str,
    port: int,
    username: str,
    password: str,
    folder: str = "INBOX",
    limit: int = 200,
    on_progress: ProgressFn | None = None,
) -> list[dict]:
    """Re-fetch the most recent messages without advancing sync cursors (for body_html backfill)."""
    conn = _connect(host, port, username, password)
    try:
        conn.select(folder, readonly=True)
        all_uids = _uids_for_search(conn, "ALL")
        if not all_uids:
            return []
        recent_uids = all_uids[-limit:]
        emails, _, _ = _fetch_uid_batch(conn, recent_uids, 0, on_progress=on_progress)
        return emails
    finally:
        try:
            conn.logout()
        except Exception:
            pass
