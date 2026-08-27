# Graph Report - email-tools  (2026-08-27)

## Corpus Check
- 30 files · ~42,173 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 642 nodes · 1466 edges · 43 communities (27 shown, 16 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 33 edges (avg confidence: 0.85)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `f3a2faaf`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- EmailStore
- Email Intelligence Studio
- routes.py
- summary.py
- imap_service.py
- Shipped (P0–P4 core + triage overhaul)
- crypto.py
- .update_job_phase
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
- .append_job_log
- .bump_verification_attempts
- .create_job
- .get_app_password_hash
- .__init__
- .set_app_password
- .update_imap_password
- test_email_parser.py
- triage.py
- test_jobs.py
- email_parser.py
- build_digest
- guess_imap_host
- sanitize_email_html
- __init__.py
- .list_inbox_thread_heads
- test_mail.py
- default_enabled_folders
- .enable_default_folders

## God Nodes (most connected - your core abstractions)
1. `EmailStore` - 131 edges
2. `get_store()` - 48 edges
3. `require_login()` - 43 edges
4. `GroqClient` - 40 edges
5. `create_app()` - 37 edges
6. `get_groq_client()` - 28 edges
7. `build_email_record()` - 21 edges
8. `_queue_job()` - 17 edges
9. `analyze_pending_emails()` - 16 edges
10. `compact_for_llm()` - 15 edges

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

## Communities (43 total, 16 thin omitted)

### Community 1 - "Email Intelligence Studio"
Cohesion: 0.09
Nodes (47): Connected Accounts, Email Intelligence Studio, Sync All Accounts, Topbar Navigation, Dashboard, Email File Import, Inbox Brief, AI Summary (+39 more)

### Community 2 - "routes.py"
Cohesion: 0.07
Nodes (99): accounts(), accounts_add(), accounts_delete(), accounts_load_older(), accounts_sync(), accounts_sync_all(), accounts_update_folders(), accounts_update_password() (+91 more)

### Community 3 - "summary.py"
Cohesion: 0.17
Nodes (18): build_email_record(), choose_category(), compact_for_llm(), compute_thread_id(), extract_keywords(), normalize_thread_subject(), Stable thread key from In-Reply-To / References, else normalized subject., Return (bullets, ai_analyzed). ai_analyzed is True when Groq produced bullets. (+10 more)

### Community 4 - "imap_service.py"
Cohesion: 0.16
Nodes (20): _connect(), fetch_emails(), fetch_recent_emails(), _fetch_uid_batch(), list_folders(), _parse_fetch_items(), _parse_uid_list(), date (+12 more)

### Community 5 - "Shipped (P0–P4 core + triage overhaul)"
Cohesion: 0.14
Nodes (12): High-leverage triage, How to use this file, IA and design, Later, Leftovers (do not treat as blockers), Mail pipeline, P4 shipped earlier, Product honesty (+4 more)

### Community 6 - "crypto.py"
Cohesion: 0.25
Nodes (10): decrypt(), decrypt_with_fallback(), _derive_material(), encrypt(), _make_fernet(), Symmetric encryption for stored IMAP passwords and Groq API keys. Uses Fernet…, Return URL-safe base64 ciphertext string., Return original plaintext, or empty string on failure. (+2 more)

### Community 8 - "create_app"
Cohesion: 0.21
Nodes (18): create_app(), _guess_imap_port(), patch, test_accounts_add_rewrites_unresolved_workspace_host(), test_api_senders_requires_auth(), test_guess_imap_port_proton(), test_help_page_mentions_workspace_imap_host(), test_help_page_public() (+10 more)

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
Cohesion: 0.06
Nodes (37): _format_http_error(), GroqClient, _is_dead_model_error(), is_fatal_groq_auth_error(), is_rate_limit_error(), _looks_like_chat_model(), _parse_bool(), _parse_json_content() (+29 more)

### Community 17 - "sync_worker.py"
Cohesion: 0.11
Nodes (30): AnalyzeFn, Any, _apply_all_ai_tags(), _apply_all_tags(), _apply_hide_ai_confirm(), Confirm hide-tag matches with Groq before hiding (or unhide false positives)., register_routes(), is_groq_unreachable() (+22 more)

### Community 18 - "Connection"
Cohesion: 0.16
Nodes (10): IMAP UIDVALIDITY and backfill cursor for incremental sync., hidden_by_tag, thread columns, FTS recipient/category alignment., Pending signup verification codes (hashed, short-lived)., IMAP sync prefs and per-folder UID checkpoints., Background job status/logs and generic per-user key-value cache., Per-phase job progress for fetch / summarize / tag / brief meters., AI tag verdict cache so Groq does not re-scan every sync., Sanitized HTML bodies and AI confirm-before-hide on tags. (+2 more)

### Community 20 - ".apply_all_manual_tags"
Cohesion: 0.14
Nodes (4): Subject/body contains rules so Hide matching works without a custom filter., Create School / Marketing / Newsletters with synonym rules when missing., Remove Marketing body rule for 'offer' — too many school false positives., Return {thread_id: [emails...]} for non-hidden mail.

### Community 31 - "test_email_parser.py"
Cohesion: 0.15
Nodes (21): expand_inline_breaks(), extract_body(), extract_body_parts(), html_to_text(), is_url_heavy_plaintext(), normalize_body_text(), _plain_prefers_html(), Return (plaintext_body, sanitized_html_body). (+13 more)

### Community 32 - "triage.py"
Cohesion: 0.14
Nodes (26): analyze_pending_emails(), Write Groq summaries + intent for unanalyzed mail. Return how many succeeded., contains_keyword(), preview_text(), analyze_heuristic_batch(), build_fyi_digest(), build_today_view(), compute_urgency() (+18 more)

### Community 33 - "test_jobs.py"
Cohesion: 0.12
Nodes (16): job_percent_from_phases(), Weighted percent across fetch / summarize / tag / brief meters., test_analyze_requires_login(), test_api_jobs_requires_auth(), test_cancel_active_job_unblocks_queue(), test_default_school_tag_matches_admissions_sender(), test_hide_matching_tag_applies_name_rules(), test_job_phase_progress_and_percent() (+8 more)

### Community 34 - "email_parser.py"
Cohesion: 0.20
Nodes (17): build_message_id(), is_mailing_list_message(), message_email_id(), normalize_text(), parse_address_header(), parse_email_upload(), parse_eml(), parse_mbox() (+9 more)

### Community 35 - "build_digest"
Cohesion: 0.15
Nodes (13): Store an inbox brief so the dashboard does not wait on Groq., refresh_cached_digest(), build_digest(), build_important_items(), clean_summary_line(), extract_links_from_text(), Return safe https/mailto links found in plain text., Escape text and linkify safe URLs for display in templates. (+5 more)

### Community 36 - "guess_imap_host"
Cohesion: 0.17
Nodes (12): _dns_name_at(), guess_imap_host(), host_resolves(), imap_host_from_mx(), lookup_mx(), _parse_mx_answers(), Map MX exchange hostnames to a known IMAP server, or empty string., Return MX exchange hostnames for *domain*. Empty on timeout or parse failure. (+4 more)

### Community 37 - "sanitize_email_html"
Cohesion: 0.29
Nodes (7): _defer_remote_images(), _image_placeholder_tag(), Sanitize email HTML for safe display with load-on-demand remote images., Replace remote images with placeholders; inline blocked schemes as text., Return safe HTML suitable for email detail view., sanitize_email_html(), test_sanitize_email_html_defers_remote_images()

### Community 38 - "__init__.py"
Cohesion: 0.33
Nodes (6): _credential_encryption_key(), _load_env_file(), _load_secret_key(), Flask, Path, Fill os.environ from `.env` without overriding vars already set.

### Community 40 - "test_mail.py"
Cohesion: 0.70
Nodes (4): _smtp_app(), test_send_email_requires_host(), test_send_email_smtps(), test_send_email_starttls()

### Community 41 - "default_enabled_folders"
Cohesion: 0.50
Nodes (4): default_enabled_folders(), is_sent_folder(), Return True when folder name looks like the provider's Sent mailbox., INBOX plus Sent-like folders enabled on first connect.

## Knowledge Gaps
- **22 isolated node(s):** `ACTIVITY_PHASES`, `How to use this file`, `What this app actually is`, `Security and boot`, `Mail pipeline` (+17 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `EmailStore` connect `EmailStore` to `summary.py`, `.update_job_phase`, `create_app`, `Connection`, `._deserialize_row`, `.apply_all_manual_tags`, `.cancel_active_jobs`, `._write_search_index`, `.append_job_log`, `.bump_verification_attempts`, `.create_job`, `.get_app_password_hash`, `.__init__`, `.set_app_password`, `.update_imap_password`, `triage.py`, `test_jobs.py`, `__init__.py`, `.list_inbox_thread_heads`, `.enable_default_folders`?**
  _High betweenness centrality (0.304) - this node is a cross-community bridge._
- **Why does `GroqClient` connect `GroqClient` to `triage.py`, `test_jobs.py`, `routes.py`, `summary.py`, `build_digest`?**
  _High betweenness centrality (0.093) - this node is a cross-community bridge._
- **Why does `create_app()` connect `create_app` to `EmailStore`, `test_jobs.py`, `routes.py`, `build_digest`, `__init__.py`, `test_mail.py`, `GroqClient`, `sync_worker.py`, `test_email_parser.py`?**
  _High betweenness centrality (0.079) - this node is a cross-community bridge._
- **What connects `ACTIVITY_PHASES`, `How to use this file`, `What this app actually is` to the rest of the system?**
  _22 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `EmailStore` be split into smaller, more focused modules?**
  _Cohesion score 0.07616892911010557 - nodes in this community are weakly interconnected._
- **Should `Email Intelligence Studio` be split into smaller, more focused modules?**
  _Cohesion score 0.08788159111933395 - nodes in this community are weakly interconnected._
- **Should `routes.py` be split into smaller, more focused modules?**
  _Cohesion score 0.07049504950495049 - nodes in this community are weakly interconnected._