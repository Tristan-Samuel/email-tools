"""Thread intent, urgency ranking, and Today view assembly."""
from __future__ import annotations

import datetime
import re
from typing import TYPE_CHECKING

from .summary import ACTION_WORDS, CATEGORY_RULES, contains_keyword, preview_text

if TYPE_CHECKING:
    from .store import EmailStore

VALID_INTENTS = frozenset({"i_owe", "waiting_on_them", "deadline", "fyi", "noise"})
DO_NOW_CAP = 8
FYI_BULLET_CAP = 6

_EMAIL_IN_SENDER_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


def extract_sender_email(sender: str) -> str:
    match = _EMAIL_IN_SENDER_RE.search(sender or "")
    return match.group(0).lower() if match else (sender or "").strip().lower()


def sender_matches_pattern(sender: str, pattern: str) -> bool:
    needle = (pattern or "").strip().lower()
    if not needle:
        return False
    hay = (sender or "").lower()
    addr = extract_sender_email(sender)
    return needle in hay or needle in addr


def sender_is_account(sender: str, account_email: str) -> bool:
    if not sender or not account_email:
        return False
    addr = extract_sender_email(sender)
    return addr == account_email.strip().lower() or account_email.strip().lower() in sender.lower()


def infer_intent_heuristic(
    email: dict,
    *,
    from_me: bool,
    last_from_me_at: str | None,
    last_inbound_at: str | None,
    vip: bool,
    always_hide: bool,
) -> tuple[str, str, str | None]:
    """Return (intent, reason, due_at)."""
    if always_hide or email.get("is_hidden"):
        return "noise", "Sender rule: always hide", None

    if from_me:
        return "waiting_on_them", "You sent the last message in this thread", None

    if email.get("is_mailing_list"):
        cat = (email.get("category") or "").lower()
        if cat in ("marketing", "newsletters"):
            return "noise", "Mailing list / promotional", None
        return "fyi", "Mailing list — no reply expected", None

    haystack = f"{email.get('subject', '')} {email.get('body', '')}"
    if any(contains_keyword(haystack, kw) for kw in CATEGORY_RULES.get("Marketing", [])):
        if "unsubscribe" in haystack.lower():
            return "noise", "Promotional bulk mail", None

    if vip:
        return "i_owe", "VIP sender — reply expected", None

    bullets = email.get("bullet_summary") or []
    bullet_text = " ".join(str(b) for b in bullets).lower()
    body = (email.get("body") or "").lower()
    asks_reply = any(w in bullet_text or w in body for w in ACTION_WORDS)
    asks_reply = asks_reply or "?" in (email.get("subject") or "")

    if last_from_me_at and last_inbound_at and last_from_me_at >= last_inbound_at:
        return "waiting_on_them", "You already replied — waiting on them", None

    if asks_reply and not from_me:
        return "i_owe", "Message asks for a response or action", None

    due_at = None
    if any(contains_keyword(haystack, kw) for kw in CATEGORY_RULES.get("Urgent", [])):
        return "deadline", "Deadline or time-sensitive language detected", due_at

    return "fyi", "Informational — no reply required", None


def compute_urgency(
    *,
    intent: str,
    due_at: str | None,
    received_at: str | None,
    vip: bool,
    today: datetime.date,
) -> int:
    score = 40
    if intent == "i_owe":
        score = 85
    elif intent == "deadline":
        score = 90
    elif intent == "waiting_on_them":
        score = 35
    elif intent == "fyi":
        score = 25
    elif intent == "noise":
        score = 5

    if vip:
        score = min(100, score + 15)

    ref = received_at or ""
    if ref:
        try:
            dt = datetime.datetime.fromisoformat(ref.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            days_old = (datetime.datetime.now(datetime.timezone.utc) - dt).days
            if intent in ("i_owe", "deadline") and days_old > 0:
                score = min(100, score + min(days_old * 3, 25))
        except ValueError:
            pass

    if due_at:
        try:
            due = datetime.date.fromisoformat(due_at[:10])
            delta = (due - today).days
            if delta < 0:
                score = min(100, score + 20)
            elif delta <= 2:
                score = min(100, score + 15)
            elif delta <= 7:
                score = min(100, score + 8)
        except ValueError:
            pass

    return max(0, min(100, score))


def days_waiting(received_at: str | None) -> int:
    if not received_at:
        return 0
    try:
        dt = datetime.datetime.fromisoformat(received_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return max(0, (datetime.datetime.now(datetime.timezone.utc) - dt).days)
    except ValueError:
        return 0


def thread_summary_text(emails: list[dict]) -> str:
    if not emails:
        return ""
    latest = emails[-1]
    bullets = latest.get("bullet_summary") or []
    if bullets:
        return str(bullets[0])
    return preview_text(latest.get("body") or latest.get("preview") or "", limit=160)


def is_do_now_intent(intent: str, triage_status: str, snooze_until: str | None, today: datetime.date) -> bool:
    if triage_status != "open":
        return False
    if snooze_until:
        try:
            if datetime.date.fromisoformat(snooze_until[:10]) > today:
                return False
        except ValueError:
            pass
    return intent in ("i_owe", "deadline")


def rebuild_thread_states(store: EmailStore, user_email: str) -> int:
    """Roll up per-thread intent from cached messages. Return threads updated."""
    accounts = store.list_imap_accounts(user_email)
    account_emails = {a["account_email"].lower() for a in accounts}
    vip_patterns = store.list_sender_rules(user_email, "vip")
    hide_patterns = store.list_sender_rules(user_email, "always_hide")
    today = datetime.date.today()

    threads = store.list_thread_groups(user_email)
    updated = 0
    for thread_id, emails in threads.items():
        if not thread_id or not emails:
            continue
        emails_sorted = sorted(emails, key=lambda e: e.get("received_at") or e.get("created_at") or "")
        latest = emails_sorted[-1]
        inbound = [e for e in emails_sorted if not e.get("from_me")]
        from_me_msgs = [e for e in emails_sorted if e.get("from_me")]
        last_inbound_at = inbound[-1].get("received_at") if inbound else None
        last_from_me_at = from_me_msgs[-1].get("received_at") if from_me_msgs else None

        sender = latest.get("sender") or ""
        vip = any(sender_matches_pattern(sender, p) for p in vip_patterns)
        always_hide = any(sender_matches_pattern(sender, p) for p in hide_patterns)

        # Prefer strongest stored intent on any open message in thread.
        intent = "fyi"
        reason = ""
        due_at = None
        triage_status = "open"
        snooze_until = None
        urgency = 0

        open_emails = [
            e
            for e in emails_sorted
            if (e.get("triage_status") or "open") == "open" and not e.get("is_hidden")
        ]
        source_email = open_emails[-1] if open_emails else latest

        stored_intent = (source_email.get("intent") or "").strip()
        if stored_intent in VALID_INTENTS:
            intent = stored_intent
            reason = source_email.get("intent_reason") or ""
            due_at = source_email.get("due_at") or None
        else:
            intent, reason, due_at = infer_intent_heuristic(
                source_email,
                from_me=bool(source_email.get("from_me")),
                last_from_me_at=last_from_me_at,
                last_inbound_at=last_inbound_at,
                vip=vip,
                always_hide=always_hide,
            )

        if vip and intent == "fyi":
            intent, reason, _ = "i_owe", "VIP sender — reply expected", due_at

        if always_hide:
            intent, reason = "noise", "Sender rule: always hide"
            for e in emails_sorted:
                if not e.get("is_hidden"):
                    store.set_email_hidden(e["email_id"], user_email, True)

        triage_status = source_email.get("triage_status") or "open"
        snooze_until = source_email.get("snooze_until")

        if last_from_me_at and last_inbound_at and last_from_me_at >= last_inbound_at:
            if intent == "i_owe" and not vip:
                intent, reason = "waiting_on_them", "You already replied — waiting on them"

        urgency = compute_urgency(
            intent=intent,
            due_at=due_at,
            received_at=last_inbound_at or latest.get("received_at"),
            vip=vip,
            today=today,
        )

        summary = thread_summary_text(emails_sorted)
        store.upsert_thread_state(
            user_email=user_email,
            thread_id=thread_id,
            summary=summary,
            intent=intent,
            intent_reason=reason,
            due_at=due_at,
            triage_status=triage_status,
            snooze_until=snooze_until,
            urgency=urgency,
            latest_email_id=latest["email_id"],
            last_inbound_at=last_inbound_at,
            last_from_me_at=last_from_me_at,
        )

        for e in emails_sorted:
            store.update_email_triage_fields(
                e["email_id"],
                user_email,
                intent=intent,
                intent_reason=reason,
                due_at=due_at,
                urgency=urgency,
            )
        updated += 1

    return updated


def build_fyi_digest(threads: list[dict], cap: int = FYI_BULLET_CAP) -> dict:
    """Local FYI rollup from thread rows (no Groq)."""
    fyi = [t for t in threads if t.get("intent") in ("fyi", "noise") and t.get("triage_status") == "open"]
    fyi.sort(key=lambda t: t.get("received_at") or "", reverse=True)
    bullets: list[dict[str, str]] = []
    for row in fyi[:cap]:
        text = row.get("summary") or row.get("subject") or "Update"
        bullets.append({"text": text, "email_id": row.get("latest_email_id") or ""})
    if not bullets:
        return {
            "headline": "Nothing new to skim.",
            "bullets": [{"text": "FYI mail is caught up.", "email_id": ""}],
            "thread_ids": [],
        }
    return {
        "headline": f"{len(fyi)} FYI thread{'s' if len(fyi) != 1 else ''} — skim or clear in one click",
        "bullets": bullets,
        "thread_ids": [t["thread_id"] for t in fyi],
    }


def build_today_view(
    store: EmailStore,
    user_email: str,
    *,
    source_account: str | None = None,
) -> dict:
    """Assemble Do now, FYI digest, and Waiting sections for Today."""
    today = datetime.date.today()
    thread_rows = store.list_thread_states(user_email, source_account=source_account)
    open_rows = [r for r in thread_rows if (r.get("triage_status") or "open") == "open" and not r.get("is_hidden")]

    do_now_candidates = [
        r
        for r in open_rows
        if is_do_now_intent(
            r.get("intent") or "fyi",
            r.get("triage_status") or "open",
            r.get("snooze_until"),
            today,
        )
    ]
    do_now_candidates.sort(key=lambda r: (-int(r.get("urgency") or 0), r.get("last_inbound_at") or ""))
    do_now = do_now_candidates[:DO_NOW_CAP]
    do_now_hidden_count = max(0, len(do_now_candidates) - DO_NOW_CAP)

    waiting = [
        r
        for r in open_rows
        if (r.get("intent") or "") == "waiting_on_them"
        and not is_do_now_intent(r.get("intent") or "", r.get("triage_status") or "open", r.get("snooze_until"), today)
    ]
    waiting.sort(key=lambda r: r.get("last_from_me_at") or "", reverse=True)
    waiting = waiting[:12]

    fyi_threads = [
        r
        for r in open_rows
        if (r.get("intent") or "") in ("fyi", "noise")
        and r["thread_id"] not in {d["thread_id"] for d in do_now}
    ]
    fyi_digest = build_fyi_digest(fyi_threads)

    for row in do_now + waiting:
        row["days_waiting"] = days_waiting(row.get("last_inbound_at") or row.get("received_at"))

    return {
        "do_now": do_now,
        "do_now_hidden_count": do_now_hidden_count,
        "waiting": waiting,
        "fyi_digest": fyi_digest,
        "open_action_count": len(do_now_candidates),
    }


def analyze_heuristic_batch(store: EmailStore, user_email: str, limit: int = 400) -> int:
    """Set intent on unanalyzed mail without Groq."""
    emails = store.list_unanalyzed_emails(user_email, limit)
    if not emails:
        return 0
    vip_patterns = store.list_sender_rules(user_email, "vip")
    hide_patterns = store.list_sender_rules(user_email, "always_hide")
    count = 0
    for email in emails:
        sender = email.get("sender") or ""
        vip = any(sender_matches_pattern(sender, p) for p in vip_patterns)
        always_hide = any(sender_matches_pattern(sender, p) for p in hide_patterns)
        intent, reason, due_at = infer_intent_heuristic(
            email,
            from_me=bool(email.get("from_me")),
            last_from_me_at=None,
            last_inbound_at=email.get("received_at"),
            vip=vip,
            always_hide=always_hide,
        )
        urgency = compute_urgency(
            intent=intent,
            due_at=due_at,
            received_at=email.get("received_at"),
            vip=vip,
            today=datetime.date.today(),
        )
        store.update_email_analysis(
            email["email_id"],
            user_email,
            bullet_summary=email.get("bullet_summary") or [],
            intent=intent,
            intent_reason=reason,
            due_at=due_at,
            urgency=urgency,
            ai_analyzed=False,
        )
        count += 1
    rebuild_thread_states(store, user_email)
    return count
