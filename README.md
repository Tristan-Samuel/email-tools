# email-tools

Flask web application for reading and triaging your inbox through AI-generated summaries — no manual email-by-email reading required.

## Features

- **Direct inbox connection** — log in with your email address and App Password to fetch emails straight from any IMAP server (Gmail, Outlook, Yahoo, iCloud, etc.). No file exports needed.
- **Multiple accounts per user** — connect as many email accounts as you like. Switch between them with the account-filter pills in the nav bar, or view everything together.
- **One-click sync** — sync a single account or all accounts at once from the dashboard or the Accounts page.
- Parse and cache every email in SQLite with full-text search.
- Auto-sort messages into categories: Urgent, Finance, Work, Alerts, Newsletters, Marketing, Personal, and more.
- Generate bullet-point summaries for each email (local heuristics or Groq AI).
- Automatically select the Groq model with the largest available context window.
- Generate an inbox-wide digest from cached summaries.
- Search across full email text, sender, subject, keywords, and cached bullet points.
- Import `.eml` and `.mbox` file exports as an alternative to direct IMAP sync.
- Modern dashboard and detailed per-email view.

## Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug
```

Then open the local Flask URL shown in the terminal.

## Adding a Groq API Key

Groq is used for AI-powered email summaries. Without a key the app falls back to local heuristic summaries that still work fine.

**Option 1 — per-user key (recommended):**
Log in, click the ⚙ icon in the nav bar → **Settings**, and paste your key from [console.groq.com](https://console.groq.com). It is stored encrypted in the database and scoped to your account.

**Option 2 — server-level key:**
Set the `GROQ_API_KEY` environment variable before starting the app. This key is used as a fallback when a user has not saved their own.

## Connecting Your Inbox

1. On the **Log In** page, enter your email address and the App Password for your provider:
   - **Gmail**: Google Account → Security → 2-Step Verification → App passwords
   - **Outlook / Hotmail**: Microsoft account security → Advanced security options → App passwords
   - **Yahoo**: Account Security → Generate app password
   - **iCloud**: Apple ID → Sign-In and Security → App-Specific Passwords
2. The IMAP host is filled in automatically based on your email domain. Expand **Advanced IMAP settings** to override it.
3. Submit the form — the app connects, saves the account, and immediately loads your 50 most recent emails.
4. Add more accounts later from **Accounts** (⚙ Accounts in the nav bar) → **+ Add Account**.

## Environment Variables

| Variable | Description |
|---|---|
| `GROQ_API_KEY` | Server-level Groq key (fallback when no per-user key is set). |
| `GROQ_DEFAULT_MODEL` | Model to use when automatic discovery fails (default: `llama-3.3-70b-versatile`). |
| `FLASK_SECRET_KEY` | Flask session secret. Set a long random string in production. |

## Project Structure

```
app.py                        Application entry point
app/
  __init__.py                 Flask app factory and configuration
  routes.py                   All routes: login, dashboard, upload, accounts, settings
  services/
    crypto.py                 Fernet encryption for stored IMAP passwords
    email_parser.py           .eml and .mbox file parsing
    groq_client.py            Groq model discovery and chat completion
    imap_service.py           IMAP connection, testing, and email fetching
    store.py                  SQLite persistence and full-text search
    summary.py                Categorisation, keyword extraction, summaries, digest
  templates/                  Jinja2 HTML templates
  static/                     CSS and JavaScript assets
instance/
  email_tools.db              SQLite database (created on first run)
  uploads/                    Temporary storage for uploaded email files
```

