"""Thread intent, urgency ranking, and Today view assembly."""
from __future__ import annotations

import datetime
import re
from typing import TYPE_CHECKING

from .summary import ACTION_WORDS, CATEGORY_RULES, contains_keyword, fill_summary_fields, preview_text

if TYPE_CHECKING:
    from .store import EmailStore

VALID_INTENTS = frozenset({"i_owe", "waiting_on_them", "deadline", "fyi", "noise"})
DO_NOW_CAP = 8
FYI_BULLET_CAP = 6
FYI_RANKED_CAP = 15
FYI_RECENT_DAYS = 14


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
    line = (latest.get("line_summary") or "").strip()
    if line:
        return line
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


def _fyi_digest_score(row: dict) -> int:
    score = int(row.get("urgency") or 0) * 10
    if not row.get("is_read"):
        score += 1000
    age = days_waiting(row.get("last_inbound_at") or row.get("received_at"))
    if age <= FYI_RECENT_DAYS:
        score += (FYI_RECENT_DAYS - age) * 5
    return score


def rebuild_thread_states(store: EmailStore, user_email: str) -> int:
    """Roll up per-thread intent from cached messages. Return threads updated."""
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

        existing = store.get_thread_state(user_email, thread_id)
        lock_active = store.thread_user_lock_active(
            existing,
            last_inbound_at=last_inbound_at,
            last_from_me_at=last_from_me_at,
            today=today,
        )

        if existing and existing.get("user_moved") and not lock_active:
            sent_last = (
                last_from_me_at
                and last_inbound_at
                and last_from_me_at >= last_inbound_at
            )
            store.clear_thread_user_lock(
                user_email,
                thread_id,
                clear_on_todo=sent_last,
            )
            existing = store.get_thread_state(user_email, thread_id)
            lock_active = False

        intent = "fyi"
        reason = ""
        due_at = None
        triage_status = "open"
        snooze_until = None

        open_emails = [
            e
            for e in emails_sorted
            if (e.get("triage_status") or "open") == "open" and not e.get("is_hidden")
        ]
        source_email = open_emails[-1] if open_emails else latest

        if lock_active and existing:
            intent = existing.get("intent") or "fyi"
            reason = existing.get("intent_reason") or ""
            due_at = existing.get("due_at")
            triage_status = existing.get("triage_status") or "open"
            snooze_until = existing.get("snooze_until")
        else:
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

            if vip and intent == "fyi" and not (
                existing and existing.get("user_action") == "remove_todo"
            ):
                intent, reason, _ = "i_owe", "VIP sender — reply expected", due_at

            triage_status = source_email.get("triage_status") or "open"
            snooze_until = source_email.get("snooze_until")

            if last_from_me_at and last_inbound_at and last_from_me_at >= last_inbound_at:
                if intent == "i_owe" and not vip:
                    intent, reason = "waiting_on_them", "You already replied — waiting on them"

        if always_hide:
            intent, reason = "noise", "Sender rule: always hide"
            for e in emails_sorted:
                if not e.get("is_hidden"):
                    store.set_email_hidden(e["email_id"], user_email, True)

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
    """Curated FYI skim — unread, recent, higher urgency (no Groq)."""
    candidates = [
        t
        for t in threads
        if (t.get("intent") or "") == "fyi"
        and (t.get("triage_status") or "open") == "open"
        and not t.get("on_todo")
    ]
    candidates.sort(key=_fyi_digest_score, reverse=True)
    shown = candidates[:cap]
    bullets: list[dict[str, str]] = []
    for row in shown:
        text = row.get("summary") or row.get("subject") or "Update"
        bullets.append(
            {
                "text": text,
                "email_id": row.get("latest_email_id") or "",
                "thread_id": row.get("thread_id") or "",
            }
        )
    if not bullets:
        return {
            "headline": "Nothing new to skim.",
            "bullets": [{"text": "FYI mail is caught up.", "email_id": "", "thread_id": ""}],
            "thread_ids": [],
            "total_pool": 0,
            "more_count": 0,
        }
    more_count = max(0, len(candidates) - len(shown))
    count = len(shown)
    headline = f"{count} recent FYI — skim or clear"
    if count != 1:
        headline += "s"
    return {
        "headline": headline,
        "bullets": bullets,
        "thread_ids": [t["thread_id"] for t in shown],
        "total_pool": len(candidates),
        "more_count": more_count,
    }


def build_today_view(
    store: EmailStore,
    user_email: str,
    *,
    source_account: str | None = None,
) -> dict:
    """Assemble Do now, FYI digest, FYI ranked list, and Waiting sections for Today."""
    today = datetime.date.today()
    thread_rows = store.list_thread_states(user_email, source_account=source_account)
    open_rows = [r for r in thread_rows if (r.get("triage_status") or "open") == "open" and not r.get("is_hidden")]

    todo_pinned = [r for r in open_rows if r.get("on_todo")]
    todo_pinned.sort(key=lambda r: (-int(r.get("urgency") or 0), r.get("last_inbound_at") or ""))

    do_now_ai = [
        r
        for r in open_rows
        if not r.get("on_todo")
        and is_do_now_intent(
            r.get("intent") or "fyi",
            r.get("triage_status") or "open",
            r.get("snooze_until"),
            today,
        )
    ]
    do_now_ai.sort(key=lambda r: (-int(r.get("urgency") or 0), r.get("last_inbound_at") or ""))
    do_now = todo_pinned + do_now_ai[:DO_NOW_CAP]
    do_now_hidden_count = max(0, len(do_now_ai) - DO_NOW_CAP)

    do_now_ids = {d["thread_id"] for d in do_now}

    waiting = [
        r
        for r in open_rows
        if (r.get("intent") or "") == "waiting_on_them"
        and r["thread_id"] not in do_now_ids
        and not is_do_now_intent(
            r.get("intent") or "",
            r.get("triage_status") or "open",
            r.get("snooze_until"),
            today,
        )
    ]
    waiting.sort(key=lambda r: r.get("last_from_me_at") or "", reverse=True)
    waiting = waiting[:12]

    fyi_pool = [
        r
        for r in open_rows
        if (r.get("intent") or "") == "fyi"
        and r["thread_id"] not in do_now_ids
        and not r.get("on_todo")
    ]
    fyi_digest = build_fyi_digest(fyi_pool)
    digest_ids = set(fyi_digest.get("thread_ids") or [])

    fyi_ranked = [
        r
        for r in fyi_pool
        if r["thread_id"] not in digest_ids
    ]
    fyi_ranked.sort(
        key=lambda r: (-int(r.get("urgency") or 0), r.get("last_inbound_at") or ""),
    )
    fyi_ranked_visible = fyi_ranked[:FYI_RANKED_CAP]
    fyi_ranked_more = fyi_ranked[FYI_RANKED_CAP:]

    for row in do_now + waiting + fyi_ranked_visible:
        row["days_waiting"] = days_waiting(row.get("last_inbound_at") or row.get("received_at"))

    return {
        "do_now": do_now,
        "do_now_hidden_count": do_now_hidden_count,
        "waiting": waiting,
        "fyi_digest": fyi_digest,
        "fyi_ranked": fyi_ranked_visible,
        "fyi_ranked_more": fyi_ranked_more,
        "open_action_count": len(todo_pinned) + len(do_now_ai),
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
        thread_id = email.get("thread_id") or email["email_id"]
        existing = store.get_thread_state(user_email, thread_id)
        today = datetime.date.today()
        if existing and store.thread_user_lock_active(
            existing,
            last_inbound_at=email.get("received_at"),
            last_from_me_at=None,
            today=today,
        ):
            continue
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
            today=today,
        )
        line, compact, bullets = fill_summary_fields(
            line=email.get("line_summary") or "",
            compact=email.get("compact_summary") or "",
            bullets=email.get("bullet_summary") or [],
            preview=email.get("preview") or "",
            sender=sender,
            subject=email.get("subject") or "",
        )
        store.update_email_analysis(
            email["email_id"],
            user_email,
            bullet_summary=bullets,
            line_summary=line,
            compact_summary=compact,
            intent=intent,
            intent_reason=reason,
            due_at=due_at,
            urgency=urgency,
            ai_analyzed=False,
        )
        count += 1
    rebuild_thread_states(store, user_email)
    return count
