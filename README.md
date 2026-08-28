# email-tools

Flask web application for triaging your inbox through AI summaries — see what still needs you on **Today**, not a message-by-message inbox.

## Features

- **Verified signup** — new accounts require a 6-digit code sent to the email address so no one can claim an address they do not own.
- **Account login** — sign in with your Inbox Tools account password. If you remove the account password, the next login requires your mailbox **App Password** from a connected IMAP account (no email-only access).
- **Multiple accounts per user** — connect as many IMAP accounts as you like. Filter with account pills in the nav bar, or view everything together.
- **Background sync with a live activity panel** — Sync All / per-account sync runs in a background queue. Stacked phase meters (Fetch / Summarize / Tag / Brief) update as mail downloads and AI analysis runs. **Cancel** stops a stuck job; the panel dismisses so it does not keep the header. A one-line strip remains when mail still needs AI analysis.
- Parse and cache every email in SQLite with full-text search (subject, sender, recipient, body, bullets, keywords, category). New mail stores **sanitized HTML** (`body_html`) for the detail view with a **Load images** button; older cached mail gets improved plaintext (forward breaks, visible links, `[image: …]` chips). Next sync backfills HTML for your recent window.
- Auto-sort messages into category signals (Urgent, Finance, Work, etc.) — **tags** are the user-facing filter taxonomy; **intent** (`i_owe`, `waiting_on_them`, `deadline`, `fyi`, `noise`) is the system triage taxonomy stored on each message and rolled up per thread. **School**, **Marketing**, and **Newsletters** tags are created on first visit. **School** never auto-hides mail (even when Marketing rules also match). Marketing/Newsletters can hide matching mail; optional **Confirm with AI before hiding** on a tag vetoes false positives. **Review hidden with AI** on the Hidden page re-checks buried mail.
- **Automatic AI analysis** — sync downloads mail quickly with local summaries, then **Gemini** (Google AI Studio) analyzes in token-budget batches (many emails per request under the 1M context window) for a **one-line list summary**, a shorter **compact** clip, key-point bullets, intent, and due date in one pass. **Groq** is the fallback when Gemini is unavailable or the daily token budget is exhausted. Groq still uses 8-email batches with per-model 429 fallback. **Today** and **All mail** have **Analyze now** (missing list-lines) and **Rescan all summaries** (regenerate every cached email). Without any AI key, heuristic intent still powers Today.
- **Today** (`/` and `/today`) — forgive-the-pile home: **Do now** (AI replies/deadlines plus anything you pin from FYI), curated **FYI digest** (recent unread skim, **Clear shown FYI** only clears what you see), **FYI by urgency** (full ranked list with Add to Do now / Dismiss), and a fold for **Waiting on them**. User triage actions are stamped on `thread_state` so rebuild and Groq cannot undo Done, Snooze, hide, or to-do placement until new inbound (or other release rules). Done / Snooze / Draft reply without opening every message.
- **All mail** (`/inbox`) — browse archive with tag filters, thread-grouped rows, split-pane preview (`?pane=1`), keyboard triage (j/k/e/u), bulk hide / read / unread + hide undo. Each row shows a dedicated one-line summary (compact clip in Compact / Titles-only views). Row order and summary size in **Settings**. **Resync all** re-downloads the current IMAP window; **Rescan summaries** regenerates AI list-lines without hitting the server.
- **Dark mode** — Light / Dark / System theme in the header menu (saved in your browser).
- **Search** — filter chips for tags, save current filters as an auto-tag, optional Ask AI when results exist, sort by urgency (default; change default in **Settings**).
- Import `.eml` and `.mbox` file exports as an alternative to IMAP.
- **Sender rules** in Settings — VIP (always surfaces on Today) and always-hide (noise). Sent folder is enabled by default on connect so the app can tell *I owe* vs *waiting on them*.
- Manual and AI tags, hide rules (manual hides preserved), thread grouping, draft reply on Today and detail. Saving a tag applies matching rules immediately; AI tags cache verdicts so the model does not re-scan every sync.

## Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug
```

Optional: copy `.env.example` to `.env` and fill in `GEMINI_API_KEY` (or `GOOGLE_API_KEY`), optional `GROQ_API_KEY`, and the `SMTP_*` values. The app loads `.env` on startup (existing shell environment variables win). Without `SMTP_HOST`, development signup shows the verification code on the page instead of emailing it.

Then open the local Flask URL shown in the terminal (lands on **Today** when logged in).

Run tests:

```bash
pytest
```

## Adding a Gemini API Key

Gemini (Google AI Studio) is the **primary** AI provider. It packs as many emails as fit into each request using a local token estimator (with optional CountTokens preflight) so you stay under rate limits (default: 15 requests/min, 1.5M tokens/day — tune `GEMINI_RPM`, `GEMINI_TPM`, `GEMINI_TPD` to match your AI Studio dashboard).

**Option 1 — per-user key (recommended):**
Log in → account menu → **Settings** → **Gemini AI (primary)**. Paste your key from [Google AI Studio](https://aistudio.google.com/apikey). It is stored **encrypted** in the database; the UI never redisplays the key.

**Option 2 — server-level key:**
Set `GEMINI_API_KEY` or `GOOGLE_API_KEY` before starting the app (used when no per-user Gemini key is set).

Default model: `gemini-3.5-flash-lite` (1M-token context, high-volume JSON). Google now 404s Gemini 2.5 for new API keys; leftover `gemini-2.5-flash-lite` / `gemini-2.5-flash` values are remapped automatically. Override with `GEMINI_DEFAULT_MODEL` (`gemini-3.1-flash-lite` and `gemini-3.6-flash` are tried if the default is unavailable).

Without a Gemini key, the app falls back to Groq (if configured) or local heuristic summaries.

## Adding a Groq API Key (fallback)

Groq is used when Gemini is unavailable, rate-limited, or the daily token budget is exhausted.

**Option 1 — per-user key (recommended):**
Log in → account menu → **Settings**. Paste your key from [console.groq.com](https://console.groq.com). It is stored **encrypted** in the database; the UI never redisplays the key.

**Option 2 — server-level key:**
Set `GROQ_API_KEY` before starting the app (fallback when no per-user key is set).

The default chat model is `openai/gpt-oss-20b` (smaller, with its own TPM bucket). Groq retired `llama-3.3-70b-versatile` on 2026-08-16. If a model returns HTTP 429, the client switches to the next live model (`qwen/qwen3.8-27b`, `qwen/qwen3.6-27b`, then `openai/gpt-oss-120b`) instead of aborting analysis. DNS or network failures fail fast with a short message and keep local summaries / stored thread intent.

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
4. Submit — the app tests IMAP, encrypts credentials, and runs an initial sync (default: mail from the last 90 days, up to 200 messages). **INBOX** and **Sent** (or provider equivalent) are enabled by default so reply-vs-waiting triage works.

On **Accounts**, each mailbox has **Mail since**, **Max messages**, folder checkboxes, **Sync now**, **Resync from server** (re-downloads the current date/count window and regenerates summaries), **Update App Password**, and **Load older mail** when more history is available on the server.

If a saved App Password cannot be decrypted (for example after changing `FLASK_SECRET_KEY`), update the password on Accounts — you do not need to delete the mailbox.

**App Password vs login password:** your Inbox Tools password logs you into this app; the mailbox App Password connects Gmail/Outlook/etc. They are different — see `/help` if unsure.

If you **remove your account password** in Settings, the next login requires the mailbox App Password from a connected account.

## Environment Variables

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | Server-level Gemini key (primary). `GOOGLE_API_KEY` is accepted as an alias. |
| `GEMINI_DEFAULT_MODEL` | Gemini model (default: `gemini-3.5-flash-lite`). Retired 2.5 IDs remap to 3.x. |
| `GEMINI_RPM` | Requests per minute for pacing (default: `15`). |
| `GEMINI_TPM` | Tokens per minute ceiling per packed request (default: `250000`). |
| `GEMINI_TPD` | Tokens per day budget tracked in SQLite (default: `1500000`). Resets at midnight Pacific. |
| `GROQ_API_KEY` | Server-level Groq key (fallback when no per-user key is set). |
| `GROQ_DEFAULT_MODEL` | Model when automatic discovery fails (default: `openai/gpt-oss-20b`). Groq retired `llama-3.3-70b-versatile` on 2026-08-16. |
| `FLASK_SECRET_KEY` | Flask session secret. **Required in production.** In development, a random key is persisted in `instance/secret_key` if unset. |
| `CREDENTIAL_ENCRYPTION_KEY` | Optional dedicated key for encrypting IMAP, Groq, and Gemini credentials at rest. If unset, derived separately from `FLASK_SECRET_KEY`. |
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
  routes.py                   All HTTP routes (login, today, inbox, search, accounts, tags, settings)
  services/
    crypto.py                 Fernet encryption for IMAP, Groq, and Gemini keys
    email_parser.py           .eml / .mbox parsing, plaintext + HTML body extraction
    html_sanitize.py          nh3 HTML sanitization and deferred remote images
    ai_client.py              Gemini-primary / Groq-fallback facade for all AI calls
    gemini_client.py          Google AI Studio client, JSON triage, token usage tracking
    token_budget.py           Local token counting and greedy email batch packing
    groq_client.py            Groq fallback: model discovery, 429 fallback, 8-email batches
    imap_service.py           IMAP connection, UID sync, Sent folder detection
    llm_text.py               URL-stripped text compaction for LLM prompts
    mail.py                   Outbound SMTP for signup verification codes
    store.py                  SQLite persistence, FTS, thread_state, sender_rules, migrations
    summary.py                Categorisation, summaries, digest, thread ids
    sync_worker.py            Background sync, auto-analyze, tagging, and job progress
    triage.py                 Intent, urgency, Today view assembly, thread rollup
  templates/                  Jinja2 HTML templates
  static/                     CSS and JavaScript assets
tests/                        pytest (store init, auth, IMAP sync mocks, triage, record fields)
instance/
  email_tools.db              SQLite database (created on first run)
  secret_key                  Auto-generated dev session secret (if FLASK_SECRET_KEY unset)
  uploads/                    Temporary upload storage (files deleted after import)
```
