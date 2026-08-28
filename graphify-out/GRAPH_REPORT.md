# Graph Report - email-tools  (2026-08-28)

## Corpus Check
- 42 files · ~59,755 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 933 nodes · 2240 edges · 44 communities (30 shown, 14 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 46 edges (avg confidence: 0.76)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `e5ff5fa3`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- EmailStore
- Email Intelligence Studio
- routes.py
- __init__.py
- imap_service.py
- Shipped (P0–P4 core + triage overhaul)
- crypto.py
- create_app
- user_prefs.py
- format_action_email_blocks
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
- BudgetLimits
- .update_email_analysis
- .create_job
- webmail.py
- gemini_client.py
- .analyze_emails_batch
- compact_for_llm
- test_webmail.py
- .enable_default_folders
- email_parser.py
- summary.py
- groq_client.py
- AiClient
- test_hide_tags.py
- GeminiQuotaTracker
- GeminiClient
- test_ai_client.py
- .append_job_log
- .update_imap_password
- _ponytail.md
- .bump_verification_attempts
- .cancel_active_jobs

## God Nodes (most connected - your core abstractions)
1. `EmailStore` - 161 edges
2. `get_store()` - 60 edges
3. `require_login()` - 54 edges
4. `AiClient` - 46 edges
5. `create_app()` - 44 edges
6. `GroqClient` - 42 edges
7. `GeminiClient` - 37 edges
8. `get_ai_client()` - 32 edges
9. `build_email_record()` - 30 edges
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
- `test_ai_confirm_tag_column()` --calls--> `EmailStore`  [EXTRACTED]
  tests/test_hide_tags.py → app/services/store.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Primary Topbar Navigation** — app_templates_base_topbar_nav, app_templates_inbox_inbox, app_templates_dashboard_dashboard, app_templates_search_advanced_search, app_templates_accounts_connected_accounts, app_templates_tags_tags, app_templates_respond_now_respond_now [EXTRACTED 1.00]
- **Groq-Powered AI Surfaces** — readme_groq_ai, app_templates_email_detail_ai_summary, app_templates_search_ask_ai, app_templates_tags_ai_classification, app_templates_respond_now_respond_now [INFERRED 0.85]
- **IMAP Inbox Connection Flow** — readme_direct_imap_connection, readme_provider_app_password, app_templates_login_login, app_templates_login_imap_host_autofill, app_templates_accounts_connected_accounts [EXTRACTED 1.00]

## Communities (44 total, 14 thin omitted)

### Community 0 - "EmailStore"
Cohesion: 0.05
Nodes (7): EmailStore, Mark mail as needing a fresh AI pass so list-line summaries can be regenerated., Zero IMAP UID checkpoints so the next sync re-downloads the current window., Update one phase meter and recompute weighted job percent., Store a hashed account password for this email-tools user., Return the stored app-password hash, or '' if none set., Release user_moved after lock exceptions (new inbound, sent reply, snooze…

### Community 1 - "Email Intelligence Studio"
Cohesion: 0.09
Nodes (47): Connected Accounts, Email Intelligence Studio, Sync All Accounts, Topbar Navigation, Dashboard, Email File Import, Inbox Brief, AI Summary (+39 more)

### Community 2 - "routes.py"
Cohesion: 0.06
Nodes (124): accounts(), accounts_add(), accounts_delete(), accounts_load_older(), accounts_resync(), accounts_resync_all(), accounts_sync(), accounts_sync_all() (+116 more)

### Community 3 - "__init__.py"
Cohesion: 0.09
Nodes (37): _credential_encryption_key(), Flask, classify_query(), classify_query_heuristic(), _extract_keywords_heuristic(), Any, Natural-language inbox search and structured AI actions., Union FTS, tag/intent heuristics, then rerank — no keyword hits required first. (+29 more)

### Community 4 - "imap_service.py"
Cohesion: 0.08
Nodes (42): _connect(), default_enabled_folders(), _dns_name_at(), fetch_emails(), fetch_recent_emails(), _fetch_uid_batch(), guess_imap_host(), host_resolves() (+34 more)

### Community 5 - "Shipped (P0–P4 core + triage overhaul)"
Cohesion: 0.14
Nodes (12): High-leverage triage, How to use this file, IA and design, Later, Leftovers (do not treat as blockers), Mail pipeline, P4 shipped earlier, Product honesty (+4 more)

### Community 6 - "crypto.py"
Cohesion: 0.25
Nodes (10): decrypt(), decrypt_with_fallback(), _derive_material(), encrypt(), _make_fernet(), Symmetric encryption for stored IMAP passwords, Groq keys, and Gemini keys.…, Return URL-safe base64 ciphertext string., Return original plaintext, or empty string on failure. (+2 more)

### Community 7 - "create_app"
Cohesion: 0.12
Nodes (29): create_app(), _load_env_file(), _load_secret_key(), Path, Fill os.environ from `.env` without overriding vars already set., _guess_imap_port(), patch, test_accounts_add_rewrites_unresolved_workspace_host() (+21 more)

### Community 8 - "user_prefs.py"
Cohesion: 0.31
Nodes (14): display_name(), fyi_cap(), get_json_pref(), get_pref(), initials(), keyboard_shortcuts_enabled(), open_in_provider(), Any (+6 more)

### Community 10 - "app.js"
Cohesion: 0.27
Nodes (5): ACTIVITY_PHASES, escapeHtml(), findIncompletePhase(), initActivityPanel(), initCommandPalette()

### Community 13 - "test_imap_sync.py"
Cohesion: 0.20
Nodes (9): _mock_conn(), patch, test_fetch_emails_failed_fetch_does_not_advance_uid(), test_fetch_emails_first_sync_sets_backfill(), test_fetch_emails_uidvalidity_resets_checkpoint(), test_fetch_uid_batch_uses_single_multi_uid_fetch(), test_guess_imap_host_google_workspace(), test_resolve_imap_host_keeps_resolvable_override() (+1 more)

### Community 15 - "mail.py"
Cohesion: 0.33
Nodes (5): Outbound email for signup verification codes (stdlib SMTP only)., Return True when SMTP_HOST is set., Return (ok, error_message)., send_email(), smtp_configured()

### Community 16 - "GroqClient"
Cohesion: 0.14
Nodes (9): GroqClient, Stop retrying a model whose TPM window is exhausted., Return a live chat model. Skips audio/TTS IDs and retired Llama defaults., Two-pass tagging: summary first, compact body only when unsure., patch, test_complete_falls_back_from_decommissioned_model(), test_complete_falls_back_from_rate_limit(), test_retired_default_model_is_remapped() (+1 more)

### Community 17 - "test_jobs.py"
Cohesion: 0.06
Nodes (53): AnalyzeFn, analyze_pending_emails(), _apply_all_ai_tags(), _apply_all_tags(), _apply_hide_ai_confirm(), _cache_ai_model(), Confirm hide-tag matches with Groq before hiding (or unhide false positives)., Write AI summaries + intent for unanalyzed mail. Return how many succeeded. (+45 more)

### Community 18 - "Connection"
Cohesion: 0.11
Nodes (15): IMAP UIDVALIDITY and backfill cursor for incremental sync., hidden_by_tag, thread columns, FTS recipient/category alignment., Pending signup verification codes (hashed, short-lived)., IMAP sync prefs and per-folder UID checkpoints., Background job status/logs and generic per-user key-value cache., Per-phase job progress for fetch / summarize / tag / brief meters., AI tag verdict cache so Groq does not re-scan every sync., Sanitized HTML bodies and AI confirm-before-hide on tags. (+7 more)

### Community 19 - "._deserialize_row"
Cohesion: 0.12
Nodes (6): Recent emails that still need an AI summary (or a dedicated list line)., Return {thread_id: [emails...]} for non-hidden mail., One row per thread — latest message metadata plus thread_state when present., Heuristic candidate pool for AI search/actions., Count emails matching the same filters as list_emails / search., Row

### Community 20 - ".apply_all_manual_tags"
Cohesion: 0.15
Nodes (4): Subject/body contains rules so Hide matching works without a custom filter., Create School / Marketing / Newsletters with synonym rules when missing., Remove Marketing body rule for 'offer' — too many school false positives., Merge AI items with due-date / school / deadline emails.

### Community 21 - "BudgetLimits"
Cohesion: 0.13
Nodes (18): BudgetLimits, format_analyze_email_block(), pack_email_batch(), Any, Token counting and greedy batch packing for Gemini email analysis., Greedy-pack as many emails as fit under TPM, context, TPD, and output budgets., Drop tail emails until optional CountTokens preflight fits., Gemini free-tier style limits (override via env to match AI Studio dashboard). (+10 more)

### Community 22 - ".update_email_analysis"
Cohesion: 0.20
Nodes (3): date, Stamp a user triage action so rebuild/Groq cannot undo it., Return True when user placement should block AI intent/status changes.

### Community 25 - "webmail.py"
Cohesion: 0.29
Nodes (9): compose_links(), compose_url(), mailto_url(), normalize_message_id(), open_message_url(), provider_for_imap_host(), Build webmail URLs for opening originals and composing replies in the user's…, Return primary https compose URL and optional mailto fallback. (+1 more)

### Community 26 - "gemini_client.py"
Cohesion: 0.15
Nodes (18): is_fatal_auth_error(), is_rate_limit_error(), Unified AI client: Gemini primary, Groq fallback., is_fatal_gemini_auth_error(), is_gemini_unreachable(), is_invalid_argument_error(), is_rate_limit_error(), is_tpd_exhausted_error() (+10 more)

### Community 28 - "compact_for_llm"
Cohesion: 0.13
Nodes (12): _parse_bool(), parse_single_summary(), Normalize summarize_email JSON into {bullets, line, compact}., Return True if AI decides this email should receive the given tag., Return True when email is commercial/promotional bulk mail worth hiding., Return a short reply draft the user can copy or open via mailto:., compact_for_llm(), Strip URLs and tracking noise before sending text to Groq. (+4 more)

### Community 31 - "email_parser.py"
Cohesion: 0.09
Nodes (41): build_message_id(), expand_inline_breaks(), extract_body(), extract_body_parts(), html_to_text(), is_mailing_list_message(), is_url_heavy_plaintext(), message_email_id() (+33 more)

### Community 32 - "summary.py"
Cohesion: 0.06
Nodes (74): _persist_email_analysis(), parse_analyze_entry(), Normalize one triage JSON item. Return None when id is missing., build_digest(), build_email_record(), build_important_items(), choose_category(), clean_summary_line() (+66 more)

### Community 33 - "groq_client.py"
Cohesion: 0.10
Nodes (16): _format_http_error(), _is_dead_model_error(), _looks_like_chat_model(), _parse_json_content(), _parse_retry_after(), _parse_tag_verdict(), Map blank or retired env/UI values to a live chat model., Short Groq error without leaking request secrets. (+8 more)

### Community 35 - "test_hide_tags.py"
Cohesion: 0.50
Nodes (3): test_ai_confirm_tag_column(), test_marketing_offer_rule_not_seeded(), test_school_tag_prevents_marketing_hide()

### Community 36 - "GeminiQuotaTracker"
Cohesion: 0.19
Nodes (4): Any, Yield (chunk, results, tokens_used) as each Gemini batch finishes., GeminiQuotaTracker, RPM pacing and per-day token usage persisted in user_kv.

### Community 37 - "GeminiClient"
Cohesion: 0.10
Nodes (16): GeminiClient, _normalize_gemini_model_id(), Return (parsed_json_or_text, error, tokens_used)., Analyze a pre-packed batch (or up to batch_size emails with compact bodies)., Map blank or 2.5-era env/UI values to a live Gemini 3.x model., resolve_gemini_model(), Client, Exception (+8 more)

### Community 38 - "test_ai_client.py"
Cohesion: 0.40
Nodes (4): patch, Tests for AiClient Gemini-primary / Groq-fallback facade., test_ai_client_falls_back_to_groq_on_gemini_failure(), test_ai_client_uses_groq_when_no_gemini_key()

## Knowledge Gaps
- **22 isolated node(s):** `ACTIVITY_PHASES`, `Ponytail, lazy senior dev mode`, `How to use this file`, `What this app actually is`, `Security and boot` (+17 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `EmailStore` connect `EmailStore` to `summary.py`, `__init__.py`, `GeminiQuotaTracker`, `test_hide_tags.py`, `.append_job_log`, `create_app`, `.update_imap_password`, `.bump_verification_attempts`, `.cancel_active_jobs`, `test_jobs.py`, `Connection`, `._deserialize_row`, `.apply_all_manual_tags`, `BudgetLimits`, `.update_email_analysis`, `.create_job`, `.enable_default_folders`?**
  _High betweenness centrality (0.276) - this node is a cross-community bridge._
- **Why does `AiClient` connect `AiClient` to `summary.py`, `routes.py`, `__init__.py`, `GeminiQuotaTracker`, `GeminiClient`, `test_ai_client.py`, `GroqClient`, `test_jobs.py`, `BudgetLimits`, `gemini_client.py`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Why does `GroqClient` connect `GroqClient` to `groq_client.py`, `routes.py`, `AiClient`, `test_ai_client.py`, `format_action_email_blocks`, `test_jobs.py`, `gemini_client.py`, `.analyze_emails_batch`, `compact_for_llm`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `EmailStore` (e.g. with `BudgetLimits` and `GeminiQuotaTracker`) actually correct?**
  _`EmailStore` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `AiClient` (e.g. with `GeminiClient` and `GroqClient`) actually correct?**
  _`AiClient` has 5 INFERRED edges - model-reasoned connections that need verification._
- **What connects `ACTIVITY_PHASES`, `Ponytail, lazy senior dev mode`, `How to use this file` to the rest of the system?**
  _22 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `EmailStore` be split into smaller, more focused modules?**
  _Cohesion score 0.0539906103286385 - nodes in this community are weakly interconnected._