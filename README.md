# email-tools

Flask web application for analyzing email exports without reading every message manually.

## Features

- Upload `.eml` and `.mbox` files from local exports.
- Parse and cache each email in SQLite.
- Log in with an email address to scope the workspace to that account.
- Auto-sort messages into categories such as Urgent, Finance, Work, Alerts, Newsletters, and more.
- Generate bullet-point summaries for each email.
- Use Groq for AI summaries and automatically select the available model with the largest context window.
- Generate an inbox-wide digest from cached summaries.
- Search across email text, sender, subject, keywords, and cached bullet points.
- Browse a modern dashboard and detailed per-email view.

## Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GROQ_API_KEY="your_groq_api_key"
flask --app app run --debug
```

Then open the local Flask URL shown in the terminal.

If `GROQ_API_KEY` is unset, the app falls back to local heuristic summaries.

## Environment Variables

- `GROQ_API_KEY`: required for Groq AI summaries.
- `GROQ_DEFAULT_MODEL`: optional fallback model if model discovery fails.
- `FLASK_SECRET_KEY`: optional Flask session secret for login sessions.

You can copy `.env.example` to `.env` and load it in your shell.

## Project Structure

- `app.py`: application entry point.
- `app/__init__.py`: Flask app factory and configuration.
- `app/routes.py`: dashboard, upload, search, and detail routes.
- `app/services/groq_client.py`: Groq model discovery and chat completion calls.
- `app/services/email_parser.py`: `.eml` and `.mbox` parsing.
- `app/services/summary.py`: categorization, keyword extraction, summaries, and digest creation.
- `app/services/store.py`: SQLite persistence and search.
- `app/templates/`: Jinja templates.
- `app/static/`: CSS and JavaScript assets.
