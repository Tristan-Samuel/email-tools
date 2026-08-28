# Graph Report - email-tools  (2026-08-28)

## Corpus Check
- 37 files · ~51,656 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 808 nodes · 1924 edges · 44 communities (29 shown, 15 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 44 edges (avg confidence: 0.76)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `ac217802`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- EmailStore
- Email Intelligence Studio
- routes.py
- test_jobs.py
- imap_service.py
- Shipped (P0–P4 core + triage overhaul)
- crypto.py
- test_summary_lines.py
- create_app
- Ponytail
- app.js
- FLASK_SECRET_KEY
- requests
- test_imap_sync.py
- conftest.py
- mail.py
- groq_client.py
- sync_worker.py
- Connection
- ._deserialize_row
- .apply_all_manual_tags
- AiClient
- .update_email_analysis
- .__init__
- rebuild_thread_states
- test_ai_client.py
- triage.py
- compact_for_llm
- .list_inbox_thread_heads
- .append_job_log
- email_parser.py
- summary.py
- .cancel_active_jobs
- ai_client.py
- .clear_ai_analyzed
- .clear_thread_user_lock
- GeminiClient
- GroqClient
- .reset_account_sync_cursors
- .set_app_password
- .update_imap_password
- .enable_default_folders
- test_store_init.py

## God Nodes (most connected - your core abstractions)
1. `EmailStore` - 150 edges
2. `get_store()` - 54 edges
3. `require_login()` - 49 edges
4. `create_app()` - 41 edges
5. `GroqClient` - 40 edges
6. `AiClient` - 39 edges
7. `get_ai_client()` - 31 edges
8. `GeminiClient` - 31 edges
9. `build_email_record()` - 28 edges
10. `compact_for_llm()` - 24 edges

## Surprising Connections (you probably didn't know these)
- `Auto-Sort Categories` --semantically_similar_to--> `Tags`  [INFERRED] [semantically similar]
  README.md → app/templates/tags.html
- `test_format_email_body_image_chip()` --calls--> `create_app()`  [EXTRACTED]
  tests/test_email_parser.py → app/__init__.py
- `test_format_email_body_linkifies_short_label_only()` --calls--> `create_app()`  [EXTRACTED]
  tests/test_email_parser.py → app/__init__.py
- `test_analyze_requires_login()` --calls--> `create_app()`  [EXTRACTED]
  tests/test_jobs.py → app/__init__.py
- `test_api_jobs_requires_auth()` --calls--> `create_app()`  [EXTRACTED]
  tests/test_jobs.py → app/__init__.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Primary Topbar Navigation** — app_templates_base_topbar_nav, app_templates_inbox_inbox, app_templates_dashboard_dashboard, app_templates_search_advanced_search, app_templates_accounts_connected_accounts, app_templates_tags_tags, app_templates_respond_now_respond_now [EXTRACTED 1.00]
- **Groq-Powered AI Surfaces** — readme_groq_ai, app_templates_email_detail_ai_summary, app_templates_search_ask_ai, app_templates_tags_ai_classification, app_templates_respond_now_respond_now [INFERRED 0.85]
- **IMAP Inbox Connection Flow** — readme_direct_imap_connection, readme_provider_app_password, app_templates_login_login, app_templates_login_imap_host_autofill, app_templates_accounts_connected_accounts [EXTRACTED 1.00]

## Communities (44 total, 15 thin omitted)

### Community 0 - "EmailStore"
Cohesion: 0.06
Nodes (5): EmailStore, Insert a queued job and return its id., Update one phase meter and recompute weighted job percent., Return the stored app-password hash, or '' if none set., Increment attempt_count and return the new value.

### Community 1 - "Email Intelligence Studio"
Cohesion: 0.09
Nodes (47): Connected Accounts, Email Intelligence Studio, Sync All Accounts, Topbar Navigation, Dashboard, Email File Import, Inbox Brief, AI Summary (+39 more)

### Community 2 - "routes.py"
Cohesion: 0.05
Nodes (126): accounts(), accounts_add(), accounts_delete(), accounts_load_older(), accounts_resync(), accounts_resync_all(), accounts_sync(), accounts_sync_all() (+118 more)

### Community 3 - "test_jobs.py"
Cohesion: 0.13
Nodes (18): job_percent_from_phases(), Weighted percent across fetch / summarize / tag / brief meters., build_email_record(), test_ai_confirm_tag_column(), test_marketing_offer_rule_not_seeded(), test_school_tag_prevents_marketing_hide(), test_analyze_requires_login(), test_api_jobs_requires_auth() (+10 more)

### Community 4 - "imap_service.py"
Cohesion: 0.09
Nodes (36): _connect(), default_enabled_folders(), _dns_name_at(), fetch_emails(), fetch_recent_emails(), _fetch_uid_batch(), guess_imap_host(), host_resolves() (+28 more)

### Community 5 - "Shipped (P0–P4 core + triage overhaul)"
Cohesion: 0.14
Nodes (12): High-leverage triage, How to use this file, IA and design, Later, Leftovers (do not treat as blockers), Mail pipeline, P4 shipped earlier, Product honesty (+4 more)

### Community 6 - "crypto.py"
Cohesion: 0.25
Nodes (10): decrypt(), decrypt_with_fallback(), _derive_material(), encrypt(), _make_fernet(), Symmetric encryption for stored IMAP passwords, Groq keys, and Gemini keys.…, Return URL-safe base64 ciphertext string., Return original plaintext, or empty string on failure. (+2 more)

### Community 7 - "test_summary_lines.py"
Cohesion: 0.16
Nodes (18): parse_analyze_entry(), Normalize one triage JSON item. Return None when id is missing., clip_at_word(), derive_compact_summary(), derive_line_summary(), email_row_summaries(), fill_summary_fields(), Truncate on a word boundary for one-line list display. (+10 more)

### Community 8 - "create_app"
Cohesion: 0.10
Nodes (32): create_app(), _credential_encryption_key(), _load_env_file(), _load_secret_key(), Flask, Path, Fill os.environ from `.env` without overriding vars already set., _guess_imap_port() (+24 more)

### Community 9 - "Ponytail"
Cohesion: 0.50
Nodes (5): Ponytail, ponytail Comment Convention, Reuse-First Ladder, Root-Cause Bug Fix, YAGNI

### Community 10 - "app.js"
Cohesion: 0.38
Nodes (4): ACTIVITY_PHASES, escapeHtml(), findIncompletePhase(), initActivityPanel()

### Community 13 - "test_imap_sync.py"
Cohesion: 0.22
Nodes (9): _mock_conn(), patch, test_fetch_emails_failed_fetch_does_not_advance_uid(), test_fetch_emails_first_sync_sets_backfill(), test_fetch_emails_uidvalidity_resets_checkpoint(), test_fetch_uid_batch_uses_single_multi_uid_fetch(), test_guess_imap_host_google_workspace(), test_resolve_imap_host_keeps_resolvable_override() (+1 more)

### Community 15 - "mail.py"
Cohesion: 0.33
Nodes (5): Outbound email for signup verification codes (stdlib SMTP only)., Return True when SMTP_HOST is set., Return (ok, error_message)., send_email(), smtp_configured()

### Community 16 - "groq_client.py"
Cohesion: 0.10
Nodes (18): _format_http_error(), _is_dead_model_error(), is_groq_unreachable(), _looks_like_chat_model(), _parse_json_content(), _parse_retry_after(), parse_single_summary(), DNS, connection, and timeout failures should not retry every model. (+10 more)

### Community 17 - "sync_worker.py"
Cohesion: 0.17
Nodes (18): AnalyzeFn, enqueue_job(), enqueue_sync(), Any, Flask, Background IMAP sync and AI analysis queue so HTTP handlers return immediately., Queue a tracked job for the background worker., Legacy helper — prefer enqueue_job with a store-created job id. (+10 more)

### Community 18 - "Connection"
Cohesion: 0.13
Nodes (13): IMAP UIDVALIDITY and backfill cursor for incremental sync., hidden_by_tag, thread columns, FTS recipient/category alignment., Pending signup verification codes (hashed, short-lived)., IMAP sync prefs and per-folder UID checkpoints., Background job status/logs and generic per-user key-value cache., Per-phase job progress for fetch / summarize / tag / brief meters., AI tag verdict cache so Groq does not re-scan every sync., Sanitized HTML bodies and AI confirm-before-hide on tags. (+5 more)

### Community 20 - ".apply_all_manual_tags"
Cohesion: 0.14
Nodes (4): Subject/body contains rules so Hide matching works without a custom filter., Create School / Marketing / Newsletters with synonym rules when missing., Remove Marketing body rule for 'offer' — too many school false positives., Return {thread_id: [emails...]} for non-hidden mail.

### Community 21 - "AiClient"
Cohesion: 0.07
Nodes (25): AiClient, Any, Yield-style batches: list of (chunk, results, tokens_used) for Gemini packing., Facade over Gemini (primary) and Groq (fallback)., BudgetLimits, format_analyze_email_block(), GeminiQuotaTracker, pacific_today() (+17 more)

### Community 22 - ".update_email_analysis"
Cohesion: 0.20
Nodes (3): date, Stamp a user triage action so rebuild/Groq cannot undo it., Return True when user placement should block AI intent/status changes.

### Community 25 - "rebuild_thread_states"
Cohesion: 0.24
Nodes (16): build_fyi_digest(), build_today_view(), infer_intent_heuristic(), Roll up per-thread intent from cached messages. Return threads updated., Curated FYI skim — unread, recent, higher urgency (no Groq)., Assemble Do now, FYI digest, FYI ranked list, and Waiting sections for Today., Return (intent, reason, due_at)., rebuild_thread_states() (+8 more)

### Community 26 - "test_ai_client.py"
Cohesion: 0.40
Nodes (4): patch, Tests for AiClient Gemini-primary / Groq-fallback facade., test_ai_client_falls_back_to_groq_on_gemini_failure(), test_ai_client_uses_groq_when_no_gemini_key()

### Community 27 - "triage.py"
Cohesion: 0.22
Nodes (13): preview_text(), analyze_heuristic_batch(), compute_urgency(), days_waiting(), extract_sender_email(), _fyi_digest_score(), is_do_now_intent(), date (+5 more)

### Community 28 - "compact_for_llm"
Cohesion: 0.16
Nodes (11): _parse_bool(), Return True if AI decides this email should receive the given tag., Return True when email is commercial/promotional bulk mail worth hiding., Return a short reply draft the user can copy or open via mailto:., compact_for_llm(), Shared text compaction for LLM prompts — no imports from provider clients., Strip URLs and tracking noise before sending text to Groq., compact_for_llm() (+3 more)

### Community 31 - "email_parser.py"
Cohesion: 0.08
Nodes (45): build_message_id(), expand_inline_breaks(), extract_body(), extract_body_parts(), html_to_text(), is_mailing_list_message(), is_url_heavy_plaintext(), message_email_id() (+37 more)

### Community 32 - "summary.py"
Cohesion: 0.17
Nodes (19): build_digest(), build_important_items(), choose_category(), clean_summary_line(), compute_thread_id(), contains_keyword(), extract_keywords(), extract_links_from_text() (+11 more)

### Community 34 - "ai_client.py"
Cohesion: 0.18
Nodes (15): is_fatal_auth_error(), is_rate_limit_error(), Unified AI client: Gemini primary, Groq fallback., is_fatal_gemini_auth_error(), is_gemini_unreachable(), is_rate_limit_error(), is_tpd_exhausted_error(), _parse_retry_after() (+7 more)

### Community 37 - "GeminiClient"
Cohesion: 0.13
Nodes (7): GeminiClient, Return (parsed_json_or_text, error, tokens_used)., Analyze a pre-packed batch (or up to batch_size emails with compact bodies)., Client, object, Tests for GeminiClient JSON parsing., test_analyze_emails_batch_parses_items()

### Community 38 - "GroqClient"
Cohesion: 0.11
Nodes (12): GroqClient, Stop retrying a model whose TPM window is exhausted., Return a live chat model. Skips audio/TTS IDs and retired Llama defaults., Two-pass tagging: summary first, compact body only when unsure., Return (items, error_message). error_message is set when the Groq call fails., Return {email_id: {bullets, intent, reason, due_at, tags}} for one Groq batch., Return {email_id: bullets} — legacy wrapper around analyze_emails_batch., patch (+4 more)

## Knowledge Gaps
- **22 isolated node(s):** `ACTIVITY_PHASES`, `How to use this file`, `What this app actually is`, `Security and boot`, `Mail pipeline` (+17 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **15 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `EmailStore` connect `EmailStore` to `test_jobs.py`, `test_summary_lines.py`, `create_app`, `sync_worker.py`, `Connection`, `._deserialize_row`, `.apply_all_manual_tags`, `AiClient`, `.update_email_analysis`, `.__init__`, `rebuild_thread_states`, `triage.py`, `.list_inbox_thread_heads`, `.append_job_log`, `.cancel_active_jobs`, `.clear_ai_analyzed`, `.clear_thread_user_lock`, `.reset_account_sync_cursors`, `.set_app_password`, `.update_imap_password`, `.enable_default_folders`, `test_store_init.py`?**
  _High betweenness centrality (0.306) - this node is a cross-community bridge._
- **Why does `GroqClient` connect `GroqClient` to `routes.py`, `ai_client.py`, `test_jobs.py`, `groq_client.py`, `AiClient`, `test_ai_client.py`, `compact_for_llm`?**
  _High betweenness centrality (0.073) - this node is a cross-community bridge._
- **Why does `create_app()` connect `create_app` to `EmailStore`, `routes.py`, `test_jobs.py`, `test_summary_lines.py`, `groq_client.py`, `rebuild_thread_states`, `email_parser.py`?**
  _High betweenness centrality (0.069) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `EmailStore` (e.g. with `BudgetLimits` and `GeminiQuotaTracker`) actually correct?**
  _`EmailStore` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `ACTIVITY_PHASES`, `How to use this file`, `What this app actually is` to the rest of the system?**
  _22 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `EmailStore` be split into smaller, more focused modules?**
  _Cohesion score 0.06487434248977206 - nodes in this community are weakly interconnected._
- **Should `Email Intelligence Studio` be split into smaller, more focused modules?**
  _Cohesion score 0.08788159111933395 - nodes in this community are weakly interconnected._