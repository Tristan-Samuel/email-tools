# Graph Report - email-tools  (2026-08-28)

## Corpus Check
- 42 files · ~58,525 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 907 nodes · 2167 edges · 42 communities (32 shown, 10 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 45 edges (avg confidence: 0.76)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `87d1270b`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- EmailStore
- Email Intelligence Studio
- routes.py
- test_ai_query.py
- imap_service.py
- Shipped (P0–P4 core + triage overhaul)
- crypto.py
- create_app
- user_prefs.py
- llm_text.py
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
- AiClient
- .update_email_analysis
- ._job_from_row
- webmail.py
- gemini_client.py
- parse_analyze_entry
- compact_for_llm
- test_webmail.py
- .enable_default_folders
- email_parser.py
- summary.py
- _response_text
- resolve_gemini_model
- test_hide_tags.py
- .set_app_password
- GeminiClient
- test_ai_client.py
- .update_job_phase
- .update_imap_password
- _ponytail.md

## God Nodes (most connected - your core abstractions)
1. `EmailStore` - 158 edges
2. `get_store()` - 59 edges
3. `require_login()` - 53 edges
4. `AiClient` - 46 edges
5. `create_app()` - 44 edges
6. `GroqClient` - 42 edges
7. `GeminiClient` - 35 edges
8. `get_ai_client()` - 32 edges
9. `build_email_record()` - 30 edges
10. `compact_for_llm()` - 24 edges

## Surprising Connections (you probably didn't know these)
- `Auto-Sort Categories` --semantically_similar_to--> `Tags`  [INFERRED] [semantically similar]
  README.md → app/templates/tags.html
- `test_format_email_body_image_chip()` --calls--> `create_app()`  [EXTRACTED]
  tests/test_email_parser.py → app/__init__.py
- `test_format_email_body_linkifies_short_label_only()` --calls--> `create_app()`  [EXTRACTED]
  tests/test_email_parser.py → app/__init__.py
- `test_retired_default_model_is_remapped()` --calls--> `GeminiClient`  [EXTRACTED]
  tests/test_gemini_client.py → app/services/gemini_client.py
- `test_groq_unreachable_detection()` --calls--> `is_groq_unreachable()`  [EXTRACTED]
  tests/test_jobs.py → app/services/groq_client.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Primary Topbar Navigation** — app_templates_base_topbar_nav, app_templates_inbox_inbox, app_templates_dashboard_dashboard, app_templates_search_advanced_search, app_templates_accounts_connected_accounts, app_templates_tags_tags, app_templates_respond_now_respond_now [EXTRACTED 1.00]
- **Groq-Powered AI Surfaces** — readme_groq_ai, app_templates_email_detail_ai_summary, app_templates_search_ask_ai, app_templates_tags_ai_classification, app_templates_respond_now_respond_now [INFERRED 0.85]
- **IMAP Inbox Connection Flow** — readme_direct_imap_connection, readme_provider_app_password, app_templates_login_login, app_templates_login_imap_host_autofill, app_templates_accounts_connected_accounts [EXTRACTED 1.00]

## Communities (42 total, 10 thin omitted)

### Community 0 - "EmailStore"
Cohesion: 0.05
Nodes (9): EmailStore, Mark mail as needing a fresh AI pass so list-line summaries can be regenerated., Zero IMAP UID checkpoints so the next sync re-downloads the current window., Mark queued/running jobs cancelled. Return cancelled job ids., Insert a queued job and return its id., Append a log line and set the job's current message to that line., Return the stored app-password hash, or '' if none set., Increment attempt_count and return the new value. (+1 more)

### Community 1 - "Email Intelligence Studio"
Cohesion: 0.09
Nodes (47): Connected Accounts, Email Intelligence Studio, Sync All Accounts, Topbar Navigation, Dashboard, Email File Import, Inbox Brief, AI Summary (+39 more)

### Community 2 - "routes.py"
Cohesion: 0.06
Nodes (126): accounts(), accounts_add(), accounts_delete(), accounts_load_older(), accounts_resync(), accounts_resync_all(), accounts_sync(), accounts_sync_all() (+118 more)

### Community 3 - "test_ai_query.py"
Cohesion: 0.18
Nodes (18): classify_query(), classify_query_heuristic(), _extract_keywords_heuristic(), Any, Natural-language inbox search and structured AI actions., Union FTS, tag/intent heuristics, then rerank — no keyword hits required first., Return structured search or action result for templates., rerank_candidates() (+10 more)

### Community 4 - "imap_service.py"
Cohesion: 0.08
Nodes (38): _connect(), default_enabled_folders(), _dns_name_at(), fetch_emails(), fetch_recent_emails(), _fetch_uid_batch(), guess_imap_host(), host_resolves() (+30 more)

### Community 5 - "Shipped (P0–P4 core + triage overhaul)"
Cohesion: 0.14
Nodes (12): High-leverage triage, How to use this file, IA and design, Later, Leftovers (do not treat as blockers), Mail pipeline, P4 shipped earlier, Product honesty (+4 more)

### Community 6 - "crypto.py"
Cohesion: 0.25
Nodes (10): decrypt(), decrypt_with_fallback(), _derive_material(), encrypt(), _make_fernet(), Symmetric encryption for stored IMAP passwords, Groq keys, and Gemini keys.…, Return URL-safe base64 ciphertext string., Return original plaintext, or empty string on failure. (+2 more)

### Community 7 - "create_app"
Cohesion: 0.06
Nodes (49): create_app(), _credential_encryption_key(), _load_env_file(), _load_secret_key(), Flask, Path, Fill os.environ from `.env` without overriding vars already set., _guess_imap_port() (+41 more)

### Community 8 - "user_prefs.py"
Cohesion: 0.31
Nodes (14): display_name(), fyi_cap(), get_json_pref(), get_pref(), initials(), keyboard_shortcuts_enabled(), open_in_provider(), Any (+6 more)

### Community 9 - "llm_text.py"
Cohesion: 0.25
Nodes (9): clean_extracted_action_items(), _email_meta(), format_action_email_blocks(), Any, Shared text compaction for LLM prompts — no imports from provider clients., Numbered email context for action extraction — no SHA-1 ids., Map Email #n / leftover hashes back to a real email_id., Normalize model JSON into {email_id, title, due_at, status, sender, subject}. (+1 more)

### Community 10 - "app.js"
Cohesion: 0.27
Nodes (5): ACTIVITY_PHASES, escapeHtml(), findIncompletePhase(), initActivityPanel(), initCommandPalette()

### Community 13 - "test_imap_sync.py"
Cohesion: 0.22
Nodes (9): _mock_conn(), patch, test_fetch_emails_failed_fetch_does_not_advance_uid(), test_fetch_emails_first_sync_sets_backfill(), test_fetch_emails_uidvalidity_resets_checkpoint(), test_fetch_uid_batch_uses_single_multi_uid_fetch(), test_guess_imap_host_google_workspace(), test_resolve_imap_host_keeps_resolvable_override() (+1 more)

### Community 15 - "mail.py"
Cohesion: 0.33
Nodes (5): Outbound email for signup verification codes (stdlib SMTP only)., Return True when SMTP_HOST is set., Return (ok, error_message)., send_email(), smtp_configured()

### Community 16 - "GroqClient"
Cohesion: 0.08
Nodes (20): _format_http_error(), GroqClient, _looks_like_chat_model(), Map blank or retired env/UI values to a live chat model., Short Groq error without leaking request secrets., Stop retrying a model whose TPM window is exhausted., Return a live chat model. Skips audio/TTS IDs and retired Llama defaults., Sleep in 1s slices. Return True if cancelled. (+12 more)

### Community 17 - "sync_worker.py"
Cohesion: 0.14
Nodes (23): AnalyzeFn, get_groq_client(), Return the Groq client only (legacy / tests). Prefer get_ai_client()., check_cancelled(), current_job_is_cancelled(), enqueue_job(), enqueue_sync(), JobCancelled (+15 more)

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
Cohesion: 0.07
Nodes (24): AiClient, Any, Yield (chunk, results, tokens_used) as each Gemini batch finishes., Facade over Gemini (primary) and Groq (fallback)., BudgetLimits, format_analyze_email_block(), GeminiQuotaTracker, pack_email_batch() (+16 more)

### Community 22 - ".update_email_analysis"
Cohesion: 0.20
Nodes (3): date, Stamp a user triage action so rebuild/Groq cannot undo it., Return True when user placement should block AI intent/status changes.

### Community 25 - "webmail.py"
Cohesion: 0.29
Nodes (9): compose_links(), compose_url(), mailto_url(), normalize_message_id(), open_message_url(), provider_for_imap_host(), Build webmail URLs for opening originals and composing replies in the user's…, Return primary https compose URL and optional mailto fallback. (+1 more)

### Community 26 - "gemini_client.py"
Cohesion: 0.14
Nodes (22): analyze_pending_emails(), Write AI summaries + intent for unanalyzed mail. Return how many succeeded., is_fatal_auth_error(), is_rate_limit_error(), is_unreachable(), Unified AI client: Gemini primary, Groq fallback., is_fatal_gemini_auth_error(), is_gemini_unreachable() (+14 more)

### Community 27 - "parse_analyze_entry"
Cohesion: 0.29
Nodes (5): parse_analyze_entry(), Return {email_id: bullets} — legacy wrapper around analyze_emails_batch., Normalize one triage JSON item. Return None when id is missing., Return {email_id: {bullets, intent, reason, due_at, tags}} for one Groq batch., test_parse_analyze_entry_reads_line_and_compact()

### Community 28 - "compact_for_llm"
Cohesion: 0.16
Nodes (9): parse_single_summary(), Normalize summarize_email JSON into {bullets, line, compact}., Return True if AI decides this email should receive the given tag., Return True when email is commercial/promotional bulk mail worth hiding., Return a short reply draft the user can copy or open via mailto:., compact_for_llm(), Strip URLs and tracking noise before sending text to Groq., test_compact_for_llm_strips_urls_keeps_labels() (+1 more)

### Community 31 - "email_parser.py"
Cohesion: 0.08
Nodes (43): build_message_id(), expand_inline_breaks(), extract_body(), extract_body_parts(), html_to_text(), is_mailing_list_message(), is_url_heavy_plaintext(), message_email_id() (+35 more)

### Community 32 - "summary.py"
Cohesion: 0.06
Nodes (73): _persist_email_analysis(), build_digest(), build_email_record(), build_important_items(), choose_category(), clean_summary_line(), clip_at_word(), compact_for_llm() (+65 more)

### Community 33 - "_response_text"
Cohesion: 0.50
Nodes (4): Any, Prefer response.text; fall back to concatenated part text (thought signatures)., _response_text(), _usage_total_tokens()

### Community 34 - "resolve_gemini_model"
Cohesion: 0.18
Nodes (10): _normalize_gemini_model_id(), Map blank or 2.5-era env/UI values to a live Gemini 3.x model., resolve_gemini_model(), Exception, object, Tests for GeminiClient JSON parsing and model fallback., test_analyze_emails_batch_parses_items(), test_generate_json_skips_404_model_on_retry() (+2 more)

### Community 35 - "test_hide_tags.py"
Cohesion: 0.50
Nodes (3): test_ai_confirm_tag_column(), test_marketing_offer_rule_not_seeded(), test_school_tag_prevents_marketing_hide()

### Community 37 - "GeminiClient"
Cohesion: 0.14
Nodes (5): GeminiClient, Return (parsed_json_or_text, error, tokens_used)., Analyze a pre-packed batch (or up to batch_size emails with compact bodies)., _parse_bool(), Client

### Community 38 - "test_ai_client.py"
Cohesion: 0.40
Nodes (4): patch, Tests for AiClient Gemini-primary / Groq-fallback facade., test_ai_client_falls_back_to_groq_on_gemini_failure(), test_ai_client_uses_groq_when_no_gemini_key()

## Knowledge Gaps
- **22 isolated node(s):** `ACTIVITY_PHASES`, `Ponytail, lazy senior dev mode`, `How to use this file`, `What this app actually is`, `Security and boot` (+17 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `EmailStore` connect `EmailStore` to `summary.py`, `test_hide_tags.py`, `.set_app_password`, `create_app`, `.update_imap_password`, `.update_job_phase`, `Connection`, `._deserialize_row`, `.apply_all_manual_tags`, `AiClient`, `.update_email_analysis`, `._job_from_row`, `.enable_default_folders`?**
  _High betweenness centrality (0.278) - this node is a cross-community bridge._
- **Why does `GroqClient` connect `GroqClient` to `routes.py`, `test_ai_client.py`, `create_app`, `llm_text.py`, `sync_worker.py`, `AiClient`, `gemini_client.py`, `parse_analyze_entry`, `compact_for_llm`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Why does `AiClient` connect `AiClient` to `summary.py`, `routes.py`, `test_ai_query.py`, `GeminiClient`, `test_ai_client.py`, `GroqClient`, `gemini_client.py`?**
  _High betweenness centrality (0.066) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `EmailStore` (e.g. with `BudgetLimits` and `GeminiQuotaTracker`) actually correct?**
  _`EmailStore` has 3 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `AiClient` (e.g. with `GeminiClient` and `GroqClient`) actually correct?**
  _`AiClient` has 5 INFERRED edges - model-reasoned connections that need verification._
- **What connects `ACTIVITY_PHASES`, `Ponytail, lazy senior dev mode`, `How to use this file` to the rest of the system?**
  _22 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `EmailStore` be split into smaller, more focused modules?**
  _Cohesion score 0.05341614906832298 - nodes in this community are weakly interconnected._