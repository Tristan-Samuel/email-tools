# Graph Report - email-tools  (2026-08-28)

## Corpus Check
- 42 files · ~58,020 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 891 nodes · 2111 edges · 45 communities (29 shown, 16 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 45 edges (avg confidence: 0.76)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `4ee59ffb`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- EmailStore
- Email Intelligence Studio
- routes.py
- ai_query.py
- imap_service.py
- Shipped (P0–P4 core + triage overhaul)
- crypto.py
- .analyze_emails_batch
- user_prefs.py
- Ponytail
- app.js
- FLASK_SECRET_KEY
- requests
- test_imap_sync.py
- conftest.py
- mail.py
- GroqClient
- test_jobs.py
- Connection
- ._deserialize_row
- .apply_all_manual_tags
- AiClient
- .update_email_analysis
- .__init__
- webmail.py
- .get_app_password_hash
- _parse_bool
- compact_for_llm
- test_webmail.py
- .enable_default_folders
- create_app
- summary.py
- .cancel_active_jobs
- gemini_client.py
- .bump_verification_attempts
- .clear_thread_user_lock
- GeminiClient
- test_ai_client.py
- .reset_account_sync_cursors
- .clear_ai_analyzed
- .create_job
- .update_imap_password
- test_store_init.py

## God Nodes (most connected - your core abstractions)
1. `EmailStore` - 157 edges
2. `get_store()` - 59 edges
3. `require_login()` - 53 edges
4. `AiClient` - 46 edges
5. `create_app()` - 42 edges
6. `GroqClient` - 42 edges
7. `GeminiClient` - 35 edges
8. `get_ai_client()` - 32 edges
9. `build_email_record()` - 28 edges
10. `compact_for_llm()` - 24 edges

## Surprising Connections (you probably didn't know these)
- `Auto-Sort Categories` --semantically_similar_to--> `Tags`  [INFERRED] [semantically similar]
  README.md → app/templates/tags.html
- `test_analyze_requires_login()` --calls--> `create_app()`  [EXTRACTED]
  tests/test_jobs.py → app/__init__.py
- `test_api_jobs_requires_auth()` --calls--> `create_app()`  [EXTRACTED]
  tests/test_jobs.py → app/__init__.py
- `test_jobs_cancel_requires_auth()` --calls--> `create_app()`  [EXTRACTED]
  tests/test_jobs.py → app/__init__.py
- `test_retired_default_model_is_remapped()` --calls--> `GeminiClient`  [EXTRACTED]
  tests/test_gemini_client.py → app/services/gemini_client.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Primary Topbar Navigation** — app_templates_base_topbar_nav, app_templates_inbox_inbox, app_templates_dashboard_dashboard, app_templates_search_advanced_search, app_templates_accounts_connected_accounts, app_templates_tags_tags, app_templates_respond_now_respond_now [EXTRACTED 1.00]
- **Groq-Powered AI Surfaces** — readme_groq_ai, app_templates_email_detail_ai_summary, app_templates_search_ask_ai, app_templates_tags_ai_classification, app_templates_respond_now_respond_now [INFERRED 0.85]
- **IMAP Inbox Connection Flow** — readme_direct_imap_connection, readme_provider_app_password, app_templates_login_login, app_templates_login_imap_host_autofill, app_templates_accounts_connected_accounts [EXTRACTED 1.00]

## Communities (45 total, 16 thin omitted)

### Community 0 - "EmailStore"
Cohesion: 0.06
Nodes (7): EmailStore, Update one phase meter and recompute weighted job percent., Append a log line and set the job's current message to that line., Store a hashed account password for this email-tools user., test_ai_confirm_tag_column(), test_marketing_offer_rule_not_seeded(), test_school_tag_prevents_marketing_hide()

### Community 1 - "Email Intelligence Studio"
Cohesion: 0.09
Nodes (47): Connected Accounts, Email Intelligence Studio, Sync All Accounts, Topbar Navigation, Dashboard, Email File Import, Inbox Brief, AI Summary (+39 more)

### Community 2 - "routes.py"
Cohesion: 0.06
Nodes (122): accounts(), accounts_add(), accounts_delete(), accounts_load_older(), accounts_resync(), accounts_resync_all(), accounts_sync(), accounts_sync_all() (+114 more)

### Community 3 - "ai_query.py"
Cohesion: 0.24
Nodes (14): classify_query(), classify_query_heuristic(), _extract_keywords_heuristic(), Any, Natural-language inbox search and structured AI actions., Union FTS, tag/intent heuristics, then rerank — no keyword hits required first., Return structured search or action result for templates., rerank_candidates() (+6 more)

### Community 4 - "imap_service.py"
Cohesion: 0.08
Nodes (38): _connect(), default_enabled_folders(), _dns_name_at(), fetch_emails(), fetch_recent_emails(), _fetch_uid_batch(), guess_imap_host(), host_resolves() (+30 more)

### Community 5 - "Shipped (P0–P4 core + triage overhaul)"
Cohesion: 0.14
Nodes (12): High-leverage triage, How to use this file, IA and design, Later, Leftovers (do not treat as blockers), Mail pipeline, P4 shipped earlier, Product honesty (+4 more)

### Community 6 - "crypto.py"
Cohesion: 0.25
Nodes (10): decrypt(), decrypt_with_fallback(), _derive_material(), encrypt(), _make_fernet(), Symmetric encryption for stored IMAP passwords, Groq keys, and Gemini keys.…, Return URL-safe base64 ciphertext string., Return original plaintext, or empty string on failure. (+2 more)

### Community 8 - "user_prefs.py"
Cohesion: 0.31
Nodes (14): display_name(), fyi_cap(), get_json_pref(), get_pref(), initials(), keyboard_shortcuts_enabled(), open_in_provider(), Any (+6 more)

### Community 9 - "Ponytail"
Cohesion: 0.50
Nodes (5): Ponytail, ponytail Comment Convention, Reuse-First Ladder, Root-Cause Bug Fix, YAGNI

### Community 10 - "app.js"
Cohesion: 0.24
Nodes (5): ACTIVITY_PHASES, escapeHtml(), findIncompletePhase(), initActivityPanel(), initCommandPalette()

### Community 13 - "test_imap_sync.py"
Cohesion: 0.22
Nodes (9): _mock_conn(), patch, test_fetch_emails_failed_fetch_does_not_advance_uid(), test_fetch_emails_first_sync_sets_backfill(), test_fetch_emails_uidvalidity_resets_checkpoint(), test_fetch_uid_batch_uses_single_multi_uid_fetch(), test_guess_imap_host_google_workspace(), test_resolve_imap_host_keeps_resolvable_override() (+1 more)

### Community 15 - "mail.py"
Cohesion: 0.33
Nodes (5): Outbound email for signup verification codes (stdlib SMTP only)., Return True when SMTP_HOST is set., Return (ok, error_message)., send_email(), smtp_configured()

### Community 16 - "GroqClient"
Cohesion: 0.09
Nodes (19): _format_http_error(), GroqClient, _is_dead_model_error(), _looks_like_chat_model(), _parse_json_content(), _parse_retry_after(), parse_single_summary(), Normalize summarize_email JSON into {bullets, line, compact}. (+11 more)

### Community 17 - "test_jobs.py"
Cohesion: 0.06
Nodes (46): AnalyzeFn, _apply_hide_ai_confirm(), Confirm hide-tag matches with Groq before hiding (or unhide false positives)., is_groq_unreachable(), DNS, connection, and timeout failures should not retry every model., job_percent_from_phases(), Weighted percent across fetch / summarize / tag / brief meters., check_cancelled() (+38 more)

### Community 18 - "Connection"
Cohesion: 0.12
Nodes (14): IMAP UIDVALIDITY and backfill cursor for incremental sync., hidden_by_tag, thread columns, FTS recipient/category alignment., Pending signup verification codes (hashed, short-lived)., IMAP sync prefs and per-folder UID checkpoints., Background job status/logs and generic per-user key-value cache., Per-phase job progress for fetch / summarize / tag / brief meters., AI tag verdict cache so Groq does not re-scan every sync., Sanitized HTML bodies and AI confirm-before-hide on tags. (+6 more)

### Community 19 - "._deserialize_row"
Cohesion: 0.12
Nodes (6): Recent emails that still need an AI summary (or a dedicated list line)., Return {thread_id: [emails...]} for non-hidden mail., One row per thread — latest message metadata plus thread_state when present., Heuristic candidate pool for AI search/actions., Count emails matching the same filters as list_emails / search., Row

### Community 20 - ".apply_all_manual_tags"
Cohesion: 0.15
Nodes (4): Subject/body contains rules so Hide matching works without a custom filter., Create School / Marketing / Newsletters with synonym rules when missing., Remove Marketing body rule for 'offer' — too many school false positives., Merge AI items with due-date / school / deadline emails.

### Community 21 - "AiClient"
Cohesion: 0.06
Nodes (37): analyze_pending_emails(), Write AI summaries + intent for unanalyzed mail. Return how many succeeded., AiClient, is_fatal_auth_error(), is_rate_limit_error(), is_unreachable(), Any, Unified AI client: Gemini primary, Groq fallback. (+29 more)

### Community 22 - ".update_email_analysis"
Cohesion: 0.20
Nodes (3): date, Stamp a user triage action so rebuild/Groq cannot undo it., Return True when user placement should block AI intent/status changes.

### Community 25 - "webmail.py"
Cohesion: 0.29
Nodes (9): compose_links(), compose_url(), mailto_url(), normalize_message_id(), open_message_url(), provider_for_imap_host(), Build webmail URLs for opening originals and composing replies in the user's…, Return primary https compose URL and optional mailto fallback. (+1 more)

### Community 27 - "_parse_bool"
Cohesion: 0.40
Nodes (3): _parse_bool(), Return True if AI decides this email should receive the given tag., Return True when email is commercial/promotional bulk mail worth hiding.

### Community 28 - "compact_for_llm"
Cohesion: 0.15
Nodes (9): _parse_tag_verdict(), Normalize yes / no / unsure from model output., Two-pass tagging: summary first, compact body only when unsure., Return a short reply draft the user can copy or open via mailto:., compact_for_llm(), Shared text compaction for LLM prompts — no imports from provider clients., Strip URLs and tracking noise before sending text to Groq., test_compact_for_llm_strips_urls_keeps_labels() (+1 more)

### Community 31 - "create_app"
Cohesion: 0.05
Nodes (72): create_app(), _credential_encryption_key(), _load_env_file(), _load_secret_key(), Flask, Path, Fill os.environ from `.env` without overriding vars already set., _guess_imap_port() (+64 more)

### Community 32 - "summary.py"
Cohesion: 0.06
Nodes (74): _persist_email_analysis(), parse_analyze_entry(), Normalize one triage JSON item. Return None when id is missing., build_digest(), build_email_record(), build_important_items(), choose_category(), clean_summary_line() (+66 more)

### Community 34 - "gemini_client.py"
Cohesion: 0.12
Nodes (17): is_unavailable_model_error(), _normalize_gemini_model_id(), _parse_retry_after(), Any, Google AI Studio / Gemini API client for email triage and summaries., Prefer response.text; fall back to concatenated part text (thought signatures)., Map blank or 2.5-era env/UI values to a live Gemini 3.x model., resolve_gemini_model() (+9 more)

### Community 37 - "GeminiClient"
Cohesion: 0.16
Nodes (4): GeminiClient, Return (parsed_json_or_text, error, tokens_used)., Analyze a pre-packed batch (or up to batch_size emails with compact bodies)., Client

### Community 38 - "test_ai_client.py"
Cohesion: 0.40
Nodes (4): patch, Tests for AiClient Gemini-primary / Groq-fallback facade., test_ai_client_falls_back_to_groq_on_gemini_failure(), test_ai_client_uses_groq_when_no_gemini_key()

## Knowledge Gaps
- **22 isolated node(s):** `ACTIVITY_PHASES`, `How to use this file`, `What this app actually is`, `Security and boot`, `Mail pipeline` (+17 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `EmailStore` connect `EmailStore` to `test_jobs.py`, `Connection`, `._deserialize_row`, `.apply_all_manual_tags`, `AiClient`, `.update_email_analysis`, `.__init__`, `.get_app_password_hash`, `.enable_default_folders`, `create_app`, `summary.py`, `.cancel_active_jobs`, `.bump_verification_attempts`, `.clear_thread_user_lock`, `.reset_account_sync_cursors`, `.clear_ai_analyzed`, `.create_job`, `.update_imap_password`, `._job_from_row`, `test_store_init.py`?**
  _High betweenness centrality (0.281) - this node is a cross-community bridge._
- **Why does `AiClient` connect `AiClient` to `summary.py`, `routes.py`, `ai_query.py`, `GeminiClient`, `test_ai_client.py`, `GroqClient`?**
  _High betweenness centrality (0.070) - this node is a cross-community bridge._
- **Why does `GroqClient` connect `GroqClient` to `routes.py`, `test_ai_client.py`, `.analyze_emails_batch`, `test_jobs.py`, `AiClient`, `_parse_bool`, `compact_for_llm`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `EmailStore` (e.g. with `BudgetLimits` and `GeminiQuotaTracker`) actually correct?**
  _`EmailStore` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `AiClient` (e.g. with `GeminiClient` and `GroqClient`) actually correct?**
  _`AiClient` has 5 INFERRED edges - model-reasoned connections that need verification._
- **What connects `ACTIVITY_PHASES`, `How to use this file`, `What this app actually is` to the rest of the system?**
  _22 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `EmailStore` be split into smaller, more focused modules?**
  _Cohesion score 0.06001984126984127 - nodes in this community are weakly interconnected._