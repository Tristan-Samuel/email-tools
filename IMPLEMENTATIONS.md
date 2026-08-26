# IMPLEMENTATIONS.md

Working audit for **email-tools**. Shipped items below are done in the current tree. Only the leftovers at the bottom are still open.

---

## How to use this file

1. Work leftovers in listed order.
2. After code changes, run `graphify update .`.
3. When you ship a leftover, check off the matching README bullet.

---

## What this app actually is

A **Flask inbox cache + Groq/heuristic triage** app. Users sign up (email verification code), log in, connect IMAP (or upload `.eml`/`.mbox`), mail is parsed, summarized, categorized, tagged, and browsed via Jinja templates. Persistence is SQLite (`EmailStore`). Outbound SMTP is used only for signup verification; no user-facing send-mail yet.

Entry: `app.py` → `create_app()` in `app/__init__.py`. All HTTP on blueprint `main` in `app/routes.py`.

---

## Shipped (P0–P4 core)

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

### Product honesty

- Needs Reply: Groq error vs empty; cache invalidated on sync; dismiss/snooze; draft reply.
- Tag apply does not unhide manual hides (`hidden_by_tag`).
- Categories are row chips / digest signals; tags are the filter taxonomy.
- Heuristic DATE_RE scheduling bullet only from a high-scoring sentence; sender/subject fallback only when body is empty.
- Proton add-account: empty host/port, JS-fill `127.0.0.1:1143`.

### IA and design

- `/` → `/inbox`; Dashboard at `/dashboard` in the account menu.
- Inbox offset pagination (cap 500). Split-pane (`?pane=1`), keyboard j/k/e/u.
- Bulk hide / unhide / read / unread + hide undo toast.
- Tag toggles have `for`/`id`.
- CSS: system UI font, 10px radius, media queries after components, no unused `.topbar-actions`.
- Branding: Inbox Tools.

### P4 shipped in this pass

1. Background queued sync and AI tag apply.
2. Split-pane inbox + keyboard.
3. Bulk actions beyond hide + undo toast.
4. Groq draft reply (copy / mailto) on Needs Reply and detail.
5. Thread grouping (`In-Reply-To` / References / normalized subject).
6. Needs Reply saved-view dismiss/snooze.

---

## Leftovers (do not treat as blockers)

### High-leverage triage

- Sender VIP / always-hide rules.
- One-click `List-Unsubscribe`.
- Follow-up tracker (“waiting on them” vs “I owe a reply”).
- Real digest brief (not keyword category counts).
- Semantic / hybrid search rerank.

### Later

SMTP send, attachments, calendar extraction, dark mode, command palette, PWA.

`app/routes.py` remains one blueprint (project rule). File is large; further extract helpers next to `sync_one_account` if it grows again.

---

*Last updated against repo layout after remaining-implementations slices 1–5.*
