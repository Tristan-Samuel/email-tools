# IMPLEMENTATIONS.md

Working audit for **email-tools**. Shipped items below are done in the current tree. Only the leftovers at the bottom are still open.

---

## How to use this file

1. Work leftovers in listed order.
2. After code changes, run `graphify update .`.
3. When you ship a leftover, check off the matching README bullet.

---

## What this app actually is

A **Flask inbox cache + Groq/heuristic triage** app. Users sign up (email verification code), log in, connect IMAP (or upload `.eml`/`.mbox`), mail is parsed, summarized, intent-tagged, categorized, tagged, and browsed via Jinja templates. **Today** is the home surface — Do now, FYI digest, Waiting — not a traditional inbox list. Persistence is SQLite (`EmailStore`). Outbound SMTP is used only for signup verification; no user-facing send-mail yet.

Entry: `app.py` → `create_app()` in `app/__init__.py`. All HTTP on blueprint `main` in `app/routes.py`.

---

## Shipped (P0–P4 core + triage overhaul)

### Security and boot

- Ordered `PRAGMA user_version` migrations; `user_settings` created first.
- Login requires account password **or** IMAP App Password + `test_connection` when the hash was removed. No email-only session.
- Signup requires a 6-digit email verification code (hashed, 10-minute TTL) before `set_app_password`.
- `FLASK_SECRET_KEY` required in production; `CREDENTIAL_ENCRYPTION_KEY` for Fernet.
- CSRF on state-changing POSTs.
- Groq key encrypted at rest; Settings never redisplays it.
- Nested forms removed; upload sanitization + temp unlink.

### Mail pipeline

- IMAP UIDVALIDITY reset, first-sync newest-N + backfill cursor, `last_uid` only on successful FETCH.
- `is_mailing_list` and `ai_analyzed` stored on ingest.
- Identity hash includes `source_account`.
- FTS5 includes subject, sender, recipient, body, bullets, keywords, category (aligned with LIKE).
- Shared `parse_message`; `sync_one_account`; background `sync_worker` queue.
- Groq chosen model cached on `current_app` keyed by API-key fingerprint.
- **Sent folder enabled by default** on account connect; `from_me` on messages for reply-vs-waiting.

### Triage-first product (2026 overhaul)

- **`thread_state` + per-email intent** — `i_owe`, `waiting_on_them`, `deadline`, `fyi`, `noise`; `triage_status`, snooze, urgency.
- **Today home** (`/` → `/today`) — Do now (capped + user-pinned to-do), curated FYI digest, FYI-by-urgency list, Waiting fold; Done / Snooze / Draft / Add to Do now / Dismiss.
- **User-action locks** on `thread_state` (`user_moved`, `on_todo`) — Groq/rebuild respect Done, Snooze, hide, and to-do placement until release (new inbound, sent reply, snooze expiry).
- **Single Groq analyze batch** — bullets + intent + due date in one pass; heuristic fallback without Groq.
- **All mail** (`/inbox`) — thread-grouped browse; detail is summary-first with body behind disclosure.
- **Sender rules** — VIP and always-hide in Settings.
- `/dashboard` and `/needs-reply` redirect to Today; dismiss/snooze persisted on threads (not ephemeral KV scan).

### Product honesty

- Tag apply does not unhide manual hides (`hidden_by_tag`).
- Categories are row chips / digest signals; tags are the filter taxonomy; intent is the system triage taxonomy.
- Heuristic DATE_RE scheduling bullet only from a high-scoring sentence; sender/subject fallback only when body is empty.
- Proton add-account: empty host/port, JS-fill `127.0.0.1:1143`.

### IA and design

- Primary nav: **Today · All mail · Search**; Tags / Accounts / Settings in account menu.
- All mail offset pagination (cap 500). Split-pane (`?pane=1`), keyboard j/k/e/u.
- Bulk hide / unhide / read / unread + hide undo toast.
- Tag toggles have `for`/`id`.
- CSS: system UI font, 10px radius, media queries after components.
- Branding: Inbox Tools.

### P4 shipped earlier

1. Background queued sync and AI tag apply.
2. Split-pane inbox + keyboard.
3. Bulk actions beyond hide + undo toast.
4. Groq draft reply (copy / mailto) on Today and detail.
5. Thread grouping (`In-Reply-To` / References / normalized subject).
6. Needs Reply dismiss/snooze → now thread triage on Today.

---

## Leftovers (do not treat as blockers)

### High-leverage triage

- One-click `List-Unsubscribe`.
- Real Groq FYI rollup brief (local digest exists; optional second rollup call).
- Semantic / hybrid search rerank.

### Later

SMTP send, attachments, calendar extraction, command palette, PWA.

`app/routes.py` remains one blueprint (project rule). File is large; further extract helpers next to `sync_one_account` if it grows again.

---

*Last updated after FYI lists, user-action locks, and Search sort.*
