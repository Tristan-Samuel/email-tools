# Graph Report - email-tools  (2026-08-26)

## Corpus Check
- 20 files · ~25,587 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 383 nodes · 834 edges · 16 communities (13 shown, 3 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 29 edges (avg confidence: 0.89)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `b3947fa0`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- EmailStore
- Email Intelligence Studio
- routes.py
- summary.py
- imap_service.py
- Shipped (P0–P4 core)
- crypto.py
- _issue_verification_code
- create_app
- Ponytail
- FLASK_SECRET_KEY
- requests
- test_imap_sync.py
- conftest.py
- mail.py

## God Nodes (most connected - your core abstractions)
1. `EmailStore` - 67 edges
2. `get_store()` - 37 edges
3. `require_login()` - 35 edges
4. `create_app()` - 22 edges
5. `get_groq_client()` - 22 edges
6. `GroqClient` - 20 edges
7. `sync_one_account()` - 15 edges
8. `build_email_record()` - 12 edges
9. `Email Intelligence Studio` - 12 edges
10. `parse_message()` - 11 edges

## Surprising Connections (you probably didn't know these)
- `Auto-Sort Categories` --semantically_similar_to--> `Tags`  [INFERRED] [semantically similar]
  README.md → app/templates/tags.html
- `test_initialize_fresh_db()` --calls--> `EmailStore`  [EXTRACTED]
  tests/test_store_init.py → app/services/store.py
- `IMAP Host Auto-Fill` --conceptually_related_to--> `Direct IMAP Inbox Connection`  [INFERRED]
  app/templates/login.html → README.md
- `AI Summary` --conceptually_related_to--> `Groq AI`  [INFERRED]
  app/templates/email_detail.html → README.md
- `Ask AI Search` --conceptually_related_to--> `Groq AI`  [INFERRED]
  app/templates/search.html → README.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Primary Topbar Navigation** — app_templates_base_topbar_nav, app_templates_inbox_inbox, app_templates_dashboard_dashboard, app_templates_search_advanced_search, app_templates_accounts_connected_accounts, app_templates_tags_tags, app_templates_respond_now_respond_now [EXTRACTED 1.00]
- **Groq-Powered AI Surfaces** — readme_groq_ai, app_templates_email_detail_ai_summary, app_templates_search_ask_ai, app_templates_tags_ai_classification, app_templates_respond_now_respond_now [INFERRED 0.85]
- **IMAP Inbox Connection Flow** — readme_direct_imap_connection, readme_provider_app_password, app_templates_login_login, app_templates_login_imap_host_autofill, app_templates_accounts_connected_accounts [EXTRACTED 1.00]

## Communities (16 total, 3 thin omitted)

### Community 0 - "EmailStore"
Cohesion: 0.06
Nodes (12): EmailStore, Path, Store a hashed account password for this email-tools user., Return the stored app-password hash, or '' if none set., Increment attempt_count and return the new value., IMAP UIDVALIDITY and backfill cursor for incremental sync., hidden_by_tag, thread columns, FTS recipient/category alignment., Pending signup verification codes (hashed, short-lived). (+4 more)

### Community 1 - "Email Intelligence Studio"
Cohesion: 0.09
Nodes (47): Connected Accounts, Email Intelligence Studio, Sync All Accounts, Topbar Navigation, Dashboard, Email File Import, Inbox Brief, AI Summary (+39 more)

### Community 2 - "routes.py"
Cohesion: 0.11
Nodes (67): accounts(), accounts_add(), accounts_delete(), accounts_load_older(), accounts_sync(), accounts_sync_all(), accounts_update_folders(), api_recipients() (+59 more)

### Community 3 - "summary.py"
Cohesion: 0.09
Nodes (30): GroqClient, _parse_bool(), _parse_json_content(), Answer a natural-language question using the provided email summaries as…, Return True if AI decides this email should receive the given tag., Return (items, error_message). error_message is set when the Groq call fails., Return a short reply draft the user can copy or open via mailto:., Return headline + bullets for the dashboard brief, or None on failure. (+22 more)

### Community 4 - "imap_service.py"
Cohesion: 0.08
Nodes (44): build_message_id(), extract_body(), is_mailing_list_message(), message_email_id(), normalize_text(), parse_address_header(), parse_email_upload(), parse_eml() (+36 more)

### Community 5 - "Shipped (P0–P4 core)"
Cohesion: 0.15
Nodes (11): High-leverage triage, How to use this file, IA and design, Later, Leftovers (do not treat as blockers), Mail pipeline, P4 shipped in this pass, Product honesty (+3 more)

### Community 6 - "crypto.py"
Cohesion: 0.31
Nodes (8): decrypt(), _derive_material(), encrypt(), _make_fernet(), Symmetric encryption for stored IMAP passwords and Groq API keys. Uses Fernet…, Return URL-safe base64 ciphertext string., Return original plaintext, or empty string on failure., Fernet

### Community 7 - "_issue_verification_code"
Cohesion: 0.24
Nodes (10): _generate_verification_code(), _issue_verification_code(), _parse_iso(), Return (sent_ok, error_message, dev_code_shown)., Create a new code, persist it, and send. Return (code_or_none, error,…, Return (ok, error_message)., _send_signup_code(), _utcnow() (+2 more)

### Community 8 - "create_app"
Cohesion: 0.09
Nodes (32): Any, create_app(), _credential_encryption_key(), _load_secret_key(), Flask, Path, _guess_imap_port(), register_routes() (+24 more)

### Community 9 - "Ponytail"
Cohesion: 0.50
Nodes (5): Ponytail, ponytail Comment Convention, Reuse-First Ladder, Root-Cause Bug Fix, YAGNI

### Community 13 - "test_imap_sync.py"
Cohesion: 0.23
Nodes (9): _mock_conn(), _mock_fetch(), patch, test_fetch_emails_failed_fetch_does_not_advance_uid(), test_fetch_emails_first_sync_sets_backfill(), test_fetch_emails_uidvalidity_resets_checkpoint(), test_guess_imap_host_google_workspace(), test_resolve_imap_host_keeps_resolvable_override() (+1 more)

### Community 15 - "mail.py"
Cohesion: 0.33
Nodes (5): Outbound email for signup verification codes (stdlib SMTP only)., Return True when SMTP_HOST is set., Return (ok, error_message)., send_email(), smtp_configured()

## Knowledge Gaps
- **20 isolated node(s):** `How to use this file`, `What this app actually is`, `Security and boot`, `Mail pipeline`, `Product honesty` (+15 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **3 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `EmailStore` connect `EmailStore` to `create_app`?**
  _High betweenness centrality (0.234) - this node is a cross-community bridge._
- **Why does `GroqClient` connect `summary.py` to `routes.py`?**
  _High betweenness centrality (0.061) - this node is a cross-community bridge._
- **Why does `create_app()` connect `create_app` to `EmailStore`?**
  _High betweenness centrality (0.051) - this node is a cross-community bridge._
- **What connects `How to use this file`, `What this app actually is`, `Security and boot` to the rest of the system?**
  _20 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `EmailStore` be split into smaller, more focused modules?**
  _Cohesion score 0.0563165905631659 - nodes in this community are weakly interconnected._
- **Should `Email Intelligence Studio` be split into smaller, more focused modules?**
  _Cohesion score 0.08788159111933395 - nodes in this community are weakly interconnected._
- **Should `routes.py` be split into smaller, more focused modules?**
  _Cohesion score 0.10613810741687979 - nodes in this community are weakly interconnected._