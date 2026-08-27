# Graph Report - email-tools  (2026-08-27)

## Corpus Check
- 30 files · ~44,542 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 661 nodes · 1534 edges · 41 communities (27 shown, 14 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 34 edges (avg confidence: 0.84)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7976fd53`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- EmailStore
- Email Intelligence Studio
- routes.py
- store.py
- imap_service.py
- Shipped (P0–P4 core + triage overhaul)
- crypto.py
- ._job_from_row
- create_app
- Ponytail
- app.js
- FLASK_SECRET_KEY
- requests
- test_imap_sync.py
- conftest.py
- mail.py
- GroqClient
- sync_worker.py
- Connection
- ._deserialize_row
- .apply_all_manual_tags
- .cancel_active_jobs
- .update_email_analysis
- .append_job_log
- .bump_verification_attempts
- .create_job
- .get_app_password_hash
- compact_for_llm
- .set_app_password
- .update_imap_password
- email_parser.py
- summary.py
- test_jobs.py
- groq_client.py
- ._complete
- .classify_emails_for_tags
- .classify_email_for_tag
- .analyze_emails_batch
- .clear_thread_user_lock
- .enable_default_folders

## God Nodes (most connected - your core abstractions)
1. `EmailStore` - 139 edges
2. `get_store()` - 51 edges
3. `require_login()` - 46 edges
4. `GroqClient` - 40 edges
5. `create_app()` - 39 edges
6. `get_groq_client()` - 28 edges
7. `build_email_record()` - 26 edges
8. `rebuild_thread_states()` - 19 edges
9. `_queue_job()` - 17 edges
10. `analyze_pending_emails()` - 16 edges

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

## Communities (41 total, 14 thin omitted)

### Community 1 - "Email Intelligence Studio"
Cohesion: 0.09
Nodes (47): Connected Accounts, Email Intelligence Studio, Sync All Accounts, Topbar Navigation, Dashboard, Email File Import, Inbox Brief, AI Summary (+39 more)

### Community 2 - "routes.py"
Cohesion: 0.06
Nodes (110): accounts(), accounts_add(), accounts_delete(), accounts_load_older(), accounts_sync(), accounts_sync_all(), accounts_update_folders(), accounts_update_password() (+102 more)

### Community 3 - "store.py"
Cohesion: 0.19
Nodes (5): Path, test_ai_confirm_tag_column(), test_marketing_offer_rule_not_seeded(), test_school_tag_prevents_marketing_hide(), test_initialize_fresh_db()

### Community 4 - "imap_service.py"
Cohesion: 0.09
Nodes (36): _connect(), default_enabled_folders(), _dns_name_at(), fetch_emails(), fetch_recent_emails(), _fetch_uid_batch(), guess_imap_host(), host_resolves() (+28 more)

### Community 5 - "Shipped (P0–P4 core + triage overhaul)"
Cohesion: 0.14
Nodes (12): High-leverage triage, How to use this file, IA and design, Later, Leftovers (do not treat as blockers), Mail pipeline, P4 shipped earlier, Product honesty (+4 more)

### Community 6 - "crypto.py"
Cohesion: 0.25
Nodes (10): decrypt(), decrypt_with_fallback(), _derive_material(), encrypt(), _make_fernet(), Symmetric encryption for stored IMAP passwords and Groq API keys. Uses Fernet…, Return URL-safe base64 ciphertext string., Return original plaintext, or empty string on failure. (+2 more)

### Community 7 - "._job_from_row"
Cohesion: 0.20
Nodes (4): job_percent_from_phases(), Update one phase meter and recompute weighted job percent., Weighted percent across fetch / summarize / tag / brief meters., test_job_phase_progress_and_percent()

### Community 8 - "create_app"
Cohesion: 0.10
Nodes (33): create_app(), _credential_encryption_key(), _load_env_file(), _load_secret_key(), Flask, Path, Fill os.environ from `.env` without overriding vars already set., _guess_imap_port() (+25 more)

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

### Community 16 - "GroqClient"
Cohesion: 0.20
Nodes (8): GroqClient, _looks_like_chat_model(), Stop retrying a model whose TPM window is exhausted., Return a live chat model. Skips audio/TTS IDs and retired Llama defaults., patch, test_complete_falls_back_from_decommissioned_model(), test_complete_falls_back_from_rate_limit(), test_summarize_emails_batch_parses_items()

### Community 17 - "sync_worker.py"
Cohesion: 0.15
Nodes (22): AnalyzeFn, Any, check_cancelled(), current_job_is_cancelled(), enqueue_job(), enqueue_sync(), JobCancelled, Flask (+14 more)

### Community 18 - "Connection"
Cohesion: 0.15
Nodes (11): IMAP UIDVALIDITY and backfill cursor for incremental sync., hidden_by_tag, thread columns, FTS recipient/category alignment., Pending signup verification codes (hashed, short-lived)., IMAP sync prefs and per-folder UID checkpoints., Background job status/logs and generic per-user key-value cache., Per-phase job progress for fetch / summarize / tag / brief meters., AI tag verdict cache so Groq does not re-scan every sync., Sanitized HTML bodies and AI confirm-before-hide on tags. (+3 more)

### Community 19 - "._deserialize_row"
Cohesion: 0.13
Nodes (5): Recent emails that still need a Groq summary., Return {thread_id: [emails...]} for non-hidden mail., One row per thread — latest message metadata plus thread_state when present., Count emails matching the same filters as list_emails / search., Row

### Community 20 - ".apply_all_manual_tags"
Cohesion: 0.18
Nodes (3): Subject/body contains rules so Hide matching works without a custom filter., Create School / Marketing / Newsletters with synonym rules when missing., Remove Marketing body rule for 'offer' — too many school false positives.

### Community 22 - ".update_email_analysis"
Cohesion: 0.20
Nodes (3): date, Stamp a user triage action so rebuild/Groq cannot undo it., Return True when user placement should block AI intent/status changes.

### Community 28 - "compact_for_llm"
Cohesion: 0.21
Nodes (8): Return a short reply draft the user can copy or open via mailto:., compact_for_llm(), Shared text compaction for Groq prompts — no imports from groq_client or…, Strip URLs and tracking noise before sending text to Groq., compact_for_llm(), Strip URLs and tracking noise before sending text to Groq., test_compact_for_llm_strips_urls_keeps_labels(), test_compact_for_llm_truncates_after_stripping()

### Community 31 - "email_parser.py"
Cohesion: 0.08
Nodes (45): build_message_id(), expand_inline_breaks(), extract_body(), extract_body_parts(), html_to_text(), is_mailing_list_message(), is_url_heavy_plaintext(), message_email_id() (+37 more)

### Community 32 - "summary.py"
Cohesion: 0.08
Nodes (50): build_digest(), build_email_record(), build_important_items(), choose_category(), clean_summary_line(), compute_thread_id(), contains_keyword(), extract_keywords() (+42 more)

### Community 33 - "test_jobs.py"
Cohesion: 0.12
Nodes (16): is_groq_unreachable(), DNS, connection, and timeout failures should not retry every model., test_analyze_requires_login(), test_api_jobs_requires_auth(), test_build_digest_bullet_objects(), test_cancel_active_job_unblocks_queue(), test_default_school_tag_matches_admissions_sender(), test_groq_unreachable_detection() (+8 more)

### Community 34 - "groq_client.py"
Cohesion: 0.20
Nodes (10): analyze_pending_emails(), Write Groq summaries + intent for unanalyzed mail. Return how many succeeded., _format_http_error(), _is_dead_model_error(), is_fatal_groq_auth_error(), is_rate_limit_error(), _parse_json_content(), _parse_retry_after() (+2 more)

### Community 35 - "._complete"
Cohesion: 0.20
Nodes (5): Sleep in 1s slices. Return True if cancelled., Return (parsed_json_or_text, error). error is set on failure., Answer a natural-language question using the provided email summaries as…, Return (items, error_message). error_message is set when the Groq call fails., Return headline + bullets for the dashboard brief, or None on failure.

### Community 36 - ".classify_emails_for_tags"
Cohesion: 0.33
Nodes (3): _parse_tag_verdict(), Normalize yes / no / unsure from model output., Two-pass tagging: summary first, compact body only when unsure.

### Community 37 - ".classify_email_for_tag"
Cohesion: 0.40
Nodes (3): _parse_bool(), Return True if AI decides this email should receive the given tag., Return True when email is commercial/promotional bulk mail worth hiding.

## Knowledge Gaps
- **22 isolated node(s):** `ACTIVITY_PHASES`, `How to use this file`, `What this app actually is`, `Security and boot`, `Mail pipeline` (+17 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `EmailStore` connect `EmailStore` to `summary.py`, `test_jobs.py`, `store.py`, `.clear_thread_user_lock`, `create_app`, `._job_from_row`, `.enable_default_folders`, `Connection`, `._deserialize_row`, `.apply_all_manual_tags`, `.cancel_active_jobs`, `.update_email_analysis`, `.append_job_log`, `.bump_verification_attempts`, `.create_job`, `.get_app_password_hash`, `.set_app_password`, `.update_imap_password`?**
  _High betweenness centrality (0.313) - this node is a cross-community bridge._
- **Why does `GroqClient` connect `GroqClient` to `summary.py`, `test_jobs.py`, `routes.py`, `._complete`, `groq_client.py`, `.classify_email_for_tag`, `.analyze_emails_batch`, `.classify_emails_for_tags`, `create_app`, `compact_for_llm`?**
  _High betweenness centrality (0.091) - this node is a cross-community bridge._
- **Why does `create_app()` connect `create_app` to `EmailStore`, `test_jobs.py`, `routes.py`, `summary.py`, `email_parser.py`?**
  _High betweenness centrality (0.080) - this node is a cross-community bridge._
- **What connects `ACTIVITY_PHASES`, `How to use this file`, `What this app actually is` to the rest of the system?**
  _22 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `EmailStore` be split into smaller, more focused modules?**
  _Cohesion score 0.07764705882352942 - nodes in this community are weakly interconnected._
- **Should `Email Intelligence Studio` be split into smaller, more focused modules?**
  _Cohesion score 0.08788159111933395 - nodes in this community are weakly interconnected._
- **Should `routes.py` be split into smaller, more focused modules?**
  _Cohesion score 0.0637065637065637 - nodes in this community are weakly interconnected._