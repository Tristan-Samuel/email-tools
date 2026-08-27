# email-tools

Flask web application for reading and triaging your inbox through AI-generated summaries — no manual email-by-email reading required.

## Features

- **Verified signup** — new accounts require a 6-digit code sent to the email address so no one can claim an address they do not own.
- **Account login** — sign in with your Inbox Tools account password. If you remove the account password, the next login requires your mailbox **App Password** from a connected IMAP account (no email-only access).
- **Multiple accounts per user** — connect as many IMAP accounts as you like. Filter with account pills in the nav bar, or view everything together.
- **Background sync with a live activity panel** — Sync All / per-account sync runs in a background queue. Stacked phase meters (Fetch / Summarize / Tag / Brief) update as mail downloads and Groq runs. **Cancel** stops a stuck job; the panel dismisses so it does not keep the header. A one-line strip remains when mail still needs AI analysis.
- Parse and cache every email in SQLite with full-text search (subject, sender, recipient, body, bullets, keywords, category). New mail stores **sanitized HTML** (`body_html`) for the detail view with a **Load images** button; older cached mail gets improved plaintext (forward breaks, visible links, `[image: …]` chips). Next sync backfills HTML for your recent window.
- Auto-sort messages into category signals (Urgent, Finance, Work, etc.) — **tags** are the user-facing filter taxonomy; categories appear as row chips. **School**, **Marketing**, and **Newsletters** tags are created on first inbox visit. **School** never auto-hides mail (even when Marketing rules also match). Marketing/Newsletters can hide matching mail; optional **Confirm with AI before hiding** on a tag vetoes false positives. **Review hidden with AI** on the Hidden page re-checks buried mail.
- **Automatic AI summaries** — sync downloads mail quickly with local summaries, then Groq analyzes in small batches. A 429 rate limit switches to another chat model (TPM is per-model) instead of stopping. Dashboard and Inbox have **Analyze now**; Settings still shows AI vs heuristic counts.
- Cached Groq model discovery (no `/models` call on every summarize). Inbox brief is generated after analysis and cached (dashboard load does not wait on Groq).
- **Dashboard** (`/dashboard`) — cached AI or local inbox brief with **clickable bullets** that open the source email, important-mail highlights with links, sync controls, unread rows with a one-line summary, and stats. Primary nav includes Inbox, Dashboard, Search, Needs Reply, and Tags.
- **Dark mode** — Light / Dark / System theme in the header menu (saved in your browser).
- **Inbox** — default landing page with tag filters, quick-tag on rows, offset pagination, split-pane preview (`?pane=1`), keyboard triage (j/k/e/u), bulk hide / read / unread + hide undo. Row order (summary / subject / sender first) and **summary size** (normal or large) in **Settings**; sender shows display name with full address on hover.
- **Search** — filter chips for tags, save current filters as an auto-tag, optional Ask AI when results exist.
- Import `.eml` and `.mbox` file exports as an alternative to IMAP.
- **Needs Reply** — Groq triage with a durable cached list (stable across refresh until new mail arrives), dismiss/snooze, and draft reply (copy / mailto). Network/DNS failures keep the last good list.
- Manual and AI tags, hide rules (manual hides preserved), thread grouping, draft reply on message detail. Saving a tag applies matching rules immediately; AI tags cache verdicts so Groq does not re-scan every sync. Hide matching without rules seeds a subject/body filter from the tag name. Hide tags can require Groq confirmation before hiding.

## Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug
```

Optional: copy `.env.example` to `.env` and fill in `GROQ_API_KEY` and the `SMTP_*` values. The app loads `.env` on startup (existing shell environment variables win). Without `SMTP_HOST`, development signup shows the verification code on the page instead of emailing it.

Then open the local Flask URL shown in the terminal (lands on **Inbox** when logged in).

Run tests:

```bash
pytest
```

## Adding a Groq API Key

Groq powers AI summaries and Needs Reply. Without a key the app uses local heuristic summaries.

**Option 1 — per-user key (recommended):**
Log in → account menu → **Settings**. Paste your key from [console.groq.com](https://console.groq.com). It is stored **encrypted** in the database; the UI never redisplays the key.

**Option 2 — server-level key:**
Set `GROQ_API_KEY` before starting the app (fallback when no per-user key is set).

The default chat model is `openai/gpt-oss-20b` (smaller, with its own TPM bucket). Groq retired `llama-3.3-70b-versatile` on 2026-08-16. If a model returns HTTP 429, the client switches to the next live model (`qwen/qwen3.8-27b`, `qwen/qwen3.6-27b`, then `openai/gpt-oss-120b`) instead of aborting analysis. DNS or network failures fail fast with a short message and keep local summaries / cached Needs Reply lists.

## Connecting Your Inbox

1. **Create an account** at `/signup` — enter your email, confirm the 6-digit verification code, and choose an Inbox Tools password.
2. Open **Accounts** from the account menu → **+ Add Account**.
3. Enter the mailbox email and **App Password** for your provider (IMAP host/port auto-fill from the email domain). See **[/help](/help)** for step-by-step instructions:
   - **Gmail**: Google Account → Security → 2-Step Verification → App passwords
   - **Google Workspace** (school/work custom domain): same App Password as Gmail; host is `imap.gmail.com` (detected from MX — not `imap.yourdomain.org`)
   - **Outlook / Hotmail / Microsoft 365**: Microsoft account security → App passwords; custom domains use `outlook.office365.com`
   - **Yahoo**: Account Security → Generate app password
   - **iCloud**: Apple ID → App-Specific Passwords
   - **Proton Mail**: install [Proton Bridge](https://proton.me/mail/bridge) — host `127.0.0.1`, port `1143` (auto-filled)
4. Submit — the app tests IMAP, encrypts credentials, and runs an initial sync (default: mail from the last 90 days, up to 200 messages).

On **Accounts**, each mailbox has **Mail since**, **Max messages**, folder checkboxes, **Sync now**, **Update App Password**, and **Load older mail** when more history is available on the server.

If a saved App Password cannot be decrypted (for example after changing `FLASK_SECRET_KEY`), update the password on Accounts — you do not need to delete the mailbox.

**App Password vs login password:** your Inbox Tools password logs you into this app; the mailbox App Password connects Gmail/Outlook/etc. They are different — see `/help` if unsure.

If you **remove your account password** in Settings, the next login requires the mailbox App Password from a connected account.

## Environment Variables

| Variable | Description |
|---|---|
| `GROQ_API_KEY` | Server-level Groq key (fallback when no per-user key is set). |
| `GROQ_DEFAULT_MODEL` | Model when automatic discovery fails (default: `openai/gpt-oss-20b`). Groq retired `llama-3.3-70b-versatile` on 2026-08-16. |
| `FLASK_SECRET_KEY` | Flask session secret. **Required in production.** In development, a random key is persisted in `instance/secret_key` if unset. |
| `CREDENTIAL_ENCRYPTION_KEY` | Optional dedicated key for encrypting IMAP and Groq credentials at rest. If unset, derived separately from `FLASK_SECRET_KEY`. |
| `SMTP_HOST` | Outbound SMTP host for signup verification emails. Required in production; if unset in development, the code is shown on the signup page. |
| `SMTP_PORT` | SMTP port (default: `587`). |
| `SMTP_USERNAME` | SMTP login username (often the sending mailbox address). |
| `SMTP_PASSWORD` | SMTP password or App Password for the sending mailbox. |
| `SMTP_FROM` | From address on verification emails (defaults to `SMTP_USERNAME`). |
| `SMTP_USE_TLS` | Use STARTTLS (default: `true`). Set `false` for SMTPS-only servers. |
| `FLASK_ENV` / `ENV` | Set to `production` to refuse startup without `FLASK_SECRET_KEY`. |

## Project Structure

```
IMPLEMENTATIONS.md            Audit + remaining follow-ups
app.py                        Application entry point
app/
  __init__.py                 Flask app factory, CSRF, configuration
  routes.py                   All HTTP routes (login, inbox, dashboard, search, accounts, tags, settings)
  services/
    crypto.py                 Fernet encryption for IMAP passwords and Groq keys
    email_parser.py           .eml / .mbox parsing, plaintext + HTML body extraction
    html_sanitize.py          nh3 HTML sanitization and deferred remote images
    groq_client.py            Groq model discovery, 429 fallback, chat, draft reply, batch summarize
    imap_service.py           IMAP connection, UID sync, batched BODY.PEEK[] fetch
    llm_text.py               URL-stripped text compaction for Groq prompts
    mail.py                   Outbound SMTP for signup verification codes
    store.py                  SQLite persistence, FTS, migrations, job logs
    summary.py                Categorisation, summaries, digest, thread ids
    sync_worker.py            Background sync, auto-analyze, tagging, and job progress
  templates/                  Jinja2 HTML templates
  static/                     CSS and JavaScript assets
tests/                        pytest (store init, auth, IMAP sync mocks, record fields)
instance/
  email_tools.db              SQLite database (created on first run)
  secret_key                  Auto-generated dev session secret (if FLASK_SECRET_KEY unset)
  uploads/                    Temporary upload storage (files deleted after import)
```
