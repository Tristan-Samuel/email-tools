from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable

import requests

from .llm_text import (
    ACTION_EXTRACT_SYSTEM,
    clean_extracted_action_items,
    compact_for_llm,
    format_action_email_blocks,
)

# Groq retired llama-3.3-70b-versatile (free/dev) on 2026-08-16.
# Prefer smaller chat models first: on-demand TPM is per-model, so a 429 on
# gpt-oss-120b still leaves gpt-oss-20b / Qwen with a fresh bucket. 20b also
# uses fewer completion tokens than 120b for the same triage JSON.
PREFERRED_CHAT_MODELS = (
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
    "qwen/qwen3.6-27b",
    "openai/gpt-oss-120b",
)
DEFAULT_CHAT_MODEL = PREFERRED_CHAT_MODELS[0]
_SKIP_MODEL_PARTS = ("whisper", "tts", "guard", "playai", "canopy", "compound")
_RETIRED_CHAT_MODELS = {
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama-3.1-70b-versatile",
    "llama-3.1-70b-specdec",
    "llama-3.3-70b-specdec",
}
_BATCH_BODY_CHARS = 800
_SINGLE_BODY_CHARS = 4000
_TAG_BODY_CHARS = 800
_TAG_SUMMARY_CHARS = 500
_JSON_MAX_TOKENS = 800
_MAX_SUMMARY_BATCH = 8


def _parse_json_content(content: str | dict) -> dict:
    if isinstance(content, dict):
        return content
    text = content.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL | re.I)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


def _parse_tag_verdict(value: object) -> str:
    """Normalize yes / no / unsure from model output."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    lowered = str(value or "").strip().lower()
    if lowered in ("yes", "true", "match", "1"):
        return "yes"
    if lowered in ("no", "false", "0"):
        return "no"
    if lowered in ("unsure", "unknown", "maybe"):
        return "unsure"
    return "unsure"


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return True if value else False
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return bool(value)


def _looks_like_chat_model(model_id: str) -> bool:
    lowered = model_id.lower()
    if lowered in _RETIRED_CHAT_MODELS:
        return False
    return not any(part in lowered for part in _SKIP_MODEL_PARTS)


def _is_dead_model_error(message: str) -> bool:
    lowered = message.lower()
    return any(
        token in lowered
        for token in (
            "decommissioned",
            "deprecated",
            "does not exist",
            "model_not_found",
            "not found",
            "unknown model",
            "invalid model",
        )
    )


def is_rate_limit_error(message: str) -> bool:
    lowered = (message or "").lower()
    return any(
        token in lowered
        for token in ("429", "rate limit", "tokens per minute", "tpm")
    )


def is_fatal_groq_auth_error(message: str) -> bool:
    lowered = (message or "").lower()
    return any(
        token in lowered
        for token in ("401", "403", "invalid api", "invalid_api_key", "incorrect api")
    )


def is_groq_unreachable(message: str) -> bool:
    """DNS, connection, and timeout failures should not retry every model."""
    lowered = (message or "").lower()
    return any(
        token in lowered
        for token in (
            "nameresolutionerror",
            "failed to resolve",
            "connectionerror",
            "connection refused",
            "timed out",
            "timeout",
            "nodename nor servname",
            "network is unreachable",
            "max retries exceeded",
        )
    )


_SUMMARY_TRIAGE_HINT = (
    "Name the organization and whether a reply is required. "
    "Do not paraphrase marketing CTAs or brochure copy. "
    "For unsolicited admissions or promo mail, say so in one line and note any real deadline."
)
_SUMMARY_LINE_HINT = (
    '"line" is a dedicated one-sentence overview for a message list (what this is and whether action is needed); '
    "do not copy the first bullet. "
    '"compact" is 6–10 words for dense lists.'
)


def parse_analyze_entry(entry: dict) -> dict | None:
    """Normalize one triage JSON item. Return None when id is missing."""
    if not isinstance(entry, dict):
        return None
    eid = str(entry.get("id") or entry.get("email_id") or "").strip()
    if not eid:
        return None
    bullets = [str(b).strip() for b in (entry.get("bullets") or []) if str(b).strip()][:4]
    line = str(entry.get("line") or entry.get("one_line") or entry.get("headline") or "").strip()
    compact = str(entry.get("compact") or entry.get("short") or "").strip()
    intent = str(entry.get("intent") or "fyi").strip().lower()
    if intent not in ("i_owe", "waiting_on_them", "deadline", "fyi", "noise"):
        intent = "fyi"
    reason = str(entry.get("reason") or "").strip()
    due_raw = str(entry.get("due_at") or "").strip()
    due_at = due_raw[:10] if due_raw and due_raw.lower() not in ("", "null", "none") else None
    raw_tags = entry.get("tags") or []
    tags = [str(t).strip() for t in raw_tags if str(t).strip()] if isinstance(raw_tags, list) else []
    return {
        "id": eid,
        "bullets": bullets,
        "line": line,
        "compact": compact,
        "intent": intent,
        "reason": reason,
        "due_at": due_at,
        "tags": tags,
    }


def parse_single_summary(parsed: dict) -> dict[str, object] | None:
    """Normalize summarize_email JSON into {bullets, line, compact}."""
    if not isinstance(parsed, dict):
        return None
    bullets = [str(b).strip() for b in (parsed.get("bullets") or []) if str(b).strip()][:4]
    line = str(parsed.get("line") or parsed.get("one_line") or parsed.get("headline") or "").strip()
    compact = str(parsed.get("compact") or parsed.get("short") or "").strip()
    if not bullets and not line:
        return None
    return {"bullets": bullets, "line": line, "compact": compact}


def _parse_retry_after(value: str | None) -> float:
    try:
        return max(0.5, min(float(value or ""), 20.0))
    except (TypeError, ValueError):
        return 2.0


def resolve_chat_model(configured: str) -> str:
    """Map blank or retired env/UI values to a live chat model."""
    configured = (configured or "").strip()
    if configured and _looks_like_chat_model(configured):
        return configured
    return DEFAULT_CHAT_MODEL


def _format_http_error(response: requests.Response) -> str:
    """Short Groq error without leaking request secrets."""
    body = (response.text or "")[:300]
    try:
        payload = response.json()
        err = payload.get("error")
        if isinstance(err, dict):
            body = str(err.get("message") or err.get("code") or body)
        elif err:
            body = str(err)
    except ValueError:
        pass
    return f"HTTP {response.status_code}: {body}".strip()


class GroqClient:
    def __init__(self, api_key: str, default_model: str):
        self.api_key = api_key.strip()
        self.default_model = resolve_chat_model(default_model)
        self.base_url = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        self._cached_best_model: str | None = None
        self._rate_limited_models: set[str] = set()
        self.last_error: str = ""
        self.last_model_used: str = ""
        self.cancel_check: Callable[[], bool] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _app_model_cache_key(self) -> str:
        fingerprint = hashlib.sha256(self.api_key.encode("utf-8")).hexdigest()[:16]
        return f"groq_model_{fingerprint}"

    def _cache_model(self, model_id: str) -> None:
        self._cached_best_model = model_id
        self._rate_limited_models.discard(model_id)
        try:
            from flask import current_app, has_app_context

            if has_app_context():
                current_app.extensions[self._app_model_cache_key()] = model_id
        except Exception:
            pass

    def _forget_cached_model(self, model_id: str) -> None:
        """Stop retrying a model whose TPM window is exhausted."""
        self._rate_limited_models.add(model_id)
        if self._cached_best_model != model_id:
            return
        self._cached_best_model = None
        try:
            from flask import current_app, has_app_context

            if has_app_context():
                current_app.extensions.pop(self._app_model_cache_key(), None)
        except Exception:
            pass

    def _models_to_try(self) -> list[str]:
        ordered: list[str] = []
        if self._cached_best_model and self._cached_best_model not in self._rate_limited_models:
            ordered.append(self._cached_best_model)
        if self.default_model not in self._rate_limited_models:
            ordered.append(self.default_model)
        ordered.extend(PREFERRED_CHAT_MODELS)
        ordered.extend(self._rate_limited_models)
        seen: set[str] = set()
        result: list[str] = []
        for model_id in ordered:
            if not model_id or model_id in seen or not _looks_like_chat_model(model_id):
                continue
            seen.add(model_id)
            result.append(model_id)
        return result

    def select_max_context_model(self) -> str:
        """Return a live chat model. Skips audio/TTS IDs and retired Llama defaults."""
        if not self.enabled:
            return self.default_model
        if self._cached_best_model and _looks_like_chat_model(self._cached_best_model):
            return self._cached_best_model

        try:
            from flask import current_app, has_app_context

            if has_app_context():
                cached = current_app.extensions.get(self._app_model_cache_key())
                if cached and _looks_like_chat_model(str(cached)):
                    self._cached_best_model = str(cached)
                    return str(cached)
        except Exception:
            pass

        live_ids = self._list_live_model_ids()
        if live_ids:
            live_set = set(live_ids)
            for preferred in PREFERRED_CHAT_MODELS:
                if preferred in live_set:
                    self._cache_model(preferred)
                    return preferred
            for model_id in live_ids:
                if _looks_like_chat_model(model_id):
                    self._cache_model(model_id)
                    return model_id

        fallback = self.default_model if _looks_like_chat_model(self.default_model) else DEFAULT_CHAT_MODEL
        self._cache_model(fallback)
        return fallback

    def _list_live_model_ids(self) -> list[str]:
        try:
            response = requests.get(
                f"{self.base_url}/models",
                headers=self._headers(),
                timeout=10,
            )
            response.raise_for_status()
            models = response.json().get("data", [])
            return [str(m.get("id")) for m in models if m.get("id")]
        except (requests.RequestException, ValueError, TypeError, KeyError):
            return []

    def _cancelled(self) -> bool:
        fn = self.cancel_check
        return bool(fn and fn())

    def _sleep_interruptible(self, seconds: float) -> bool:
        """Sleep in 1s slices. Return True if cancelled."""
        remaining = max(0.0, seconds)
        while remaining > 0:
            if self._cancelled():
                return True
            step = min(1.0, remaining)
            time.sleep(step)
            remaining -= step
        return self._cancelled()

    def _complete(
        self,
        messages: list[dict],
        *,
        json_mode: bool = True,
        temperature: float = 0.2,
        timeout: int = 45,
    ) -> tuple[dict | str | None, str | None]:
        """Return (parsed_json_or_text, error). error is set on failure."""
        if not self.enabled:
            self.last_error = "Groq API key is missing."
            return None, self.last_error

        last_err = ""
        retry_wait = 0.0
        use_json = json_mode
        for attempt in range(2):
            if self._cancelled():
                self.last_error = "Cancelled."
                return None, self.last_error
            if attempt == 1:
                if retry_wait <= 0:
                    break
                if self._sleep_interruptible(retry_wait):
                    self.last_error = "Cancelled."
                    return None, self.last_error
            for model_name in self._models_to_try():
                if self._cancelled():
                    self.last_error = "Cancelled."
                    return None, self.last_error
                if attempt == 0 and model_name in self._rate_limited_models:
                    continue
                payload: dict = {
                    "model": model_name,
                    "temperature": temperature,
                    "messages": messages,
                    "max_tokens": _JSON_MAX_TOKENS if use_json else 900,
                }
                if use_json:
                    payload["response_format"] = {"type": "json_object"}
                try:
                    response = requests.post(
                        f"{self.base_url}/chat/completions",
                        headers=self._headers(),
                        json=payload,
                        timeout=timeout,
                    )
                except requests.RequestException as exc:
                    last_err = str(exc)
                    if is_groq_unreachable(last_err):
                        self.last_error = (
                            "Can't reach Groq (network or DNS). Local summaries are still available."
                        )
                        return None, self.last_error
                    continue

                if response.status_code == 429:
                    last_err = _format_http_error(response)
                    self._forget_cached_model(model_name)
                    retry_wait = max(
                        retry_wait,
                        _parse_retry_after(response.headers.get("Retry-After")),
                    )
                    continue

                if response.status_code in (400, 404) and _is_dead_model_error(_format_http_error(response)):
                    last_err = _format_http_error(response)
                    continue

                if not response.ok:
                    last_err = _format_http_error(response)
                    if use_json and response.status_code == 400 and "json" in last_err.lower():
                        use_json = False
                    continue

                try:
                    content = response.json()["choices"][0]["message"]["content"]
                except (ValueError, KeyError, TypeError, IndexError):
                    last_err = "Groq returned a response we could not parse."
                    continue

                self._cache_model(model_name)
                self.last_model_used = model_name
                self.last_error = ""
                if use_json:
                    try:
                        return _parse_json_content(content), None
                    except (ValueError, TypeError):
                        last_err = "Groq returned invalid JSON."
                        continue
                return str(content).strip(), None

        self.last_error = last_err or "Groq request failed."
        return None, self.last_error

    def summarize_email(self, sender: str, subject: str, body: str) -> dict[str, object] | None:
        if not self.enabled:
            return None

        clipped_body = compact_for_llm(body, _SINGLE_BODY_CHARS)
        prompt = (
            "Summarize this email for inbox triage. Return JSON only with keys "
            '"line" (one sentence for a message list), '
            '"compact" (6–10 words for a dense list), and '
            '"bullets" (up to 4 distinct key points). '
            f"{_SUMMARY_LINE_HINT} {_SUMMARY_TRIAGE_HINT}"
        )
        parsed, _err = self._complete(
            [
                {"role": "system", "content": "You produce strict JSON."},
                {
                    "role": "user",
                    "content": (
                        f"{prompt}\n\n"
                        f"Sender: {sender or 'Unknown sender'}\n"
                        f"Subject: {subject}\n"
                        f"Body:\n{clipped_body}"
                    ),
                },
            ],
            timeout=30,
        )
        return parse_single_summary(parsed) if isinstance(parsed, dict) else None

    def answer_about_emails(self, question: str, emails: list[dict]) -> str | None:
        """Answer a natural-language question using the provided email summaries as context."""
        if not self.enabled or not emails:
            return None

        context_parts = []
        for i, e in enumerate(emails[:20], 1):
            bullets = e.get("bullet_summary") or []
            summary = " ".join(bullets) if bullets else (e.get("preview") or "")
            context_parts.append(
                f"#{i} From: {e.get('sender', '?')} | Subject: {e.get('subject', '?')}\n{summary}"
            )
        context = "\n\n".join(context_parts)
        parsed, _err = self._complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a helpful email assistant. The user will ask a question about their emails. "
                        "Answer in a few short sentences or a simple bullet list using only the summaries. "
                        "Never mention email IDs or hashes. Do not use a 'Key actions:' heading. "
                        "If you can't answer from the emails, say so briefly."
                    ),
                },
                {
                    "role": "user",
                    "content": f"My emails:\n\n{context}\n\nQuestion: {question}",
                },
            ],
            json_mode=False,
            temperature=0.3,
            timeout=30,
        )
        return parsed if isinstance(parsed, str) and parsed else None

    def classify_inbox_query(self, prompt: str) -> dict | None:
        if not self.enabled or not (prompt or "").strip():
            return None
        parsed, _err = self._complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Classify an inbox assistant query. Return JSON only: "
                        '{"mode": "search"|"action", "action_type": "list_assignments"|"waiting_on_me"|'
                        '"this_week"|"find_topic"|"custom", "keywords": ["word1", "word2"]}. '
                        "mode=search when finding emails; mode=action when extracting a task list."
                    ),
                },
                {"role": "user", "content": f"User query: {prompt.strip()}"},
            ],
            temperature=0.1,
            timeout=20,
        )
        if not isinstance(parsed, dict):
            return None
        mode = str(parsed.get("mode") or "search").strip().lower()
        action_type = str(parsed.get("action_type") or "find_topic").strip().lower()
        raw_kw = parsed.get("keywords") or []
        keywords = [str(k).strip() for k in raw_kw if str(k).strip()] if isinstance(raw_kw, list) else []
        if mode not in ("search", "action"):
            mode = "search"
        if action_type not in (
            "list_assignments", "waiting_on_me", "this_week", "find_topic", "custom",
        ):
            action_type = "find_topic"
        return {"mode": mode, "action_type": action_type, "keywords": keywords[:8]}

    def extract_action_items(
        self,
        prompt: str,
        action_type: str,
        emails: list[dict],
        today: str = "",
    ) -> tuple[list[dict], str | None]:
        if not self.enabled or not emails:
            return [], self.last_error or "No emails to analyze."
        context = format_action_email_blocks(emails, 30)
        today_line = f"Today's date: {today}\n" if today else ""
        parsed, err = self._complete(
            [
                {
                    "role": "system",
                    "content": ACTION_EXTRACT_SYSTEM,
                },
                {
                    "role": "user",
                    "content": (
                        f"{today_line}Action type: {action_type}\n"
                        f"User request: {prompt}\n\nEmails:\n\n{context}"
                    ),
                },
            ],
            temperature=0.1,
            timeout=40,
        )
        if not isinstance(parsed, dict):
            return [], err
        return clean_extracted_action_items(parsed.get("items"), emails[:30]), None

    def classify_email_for_tag(
        self,
        tag_name: str,
        ai_instruction: str,
        sender: str,
        subject: str,
        body: str,
    ) -> bool:
        """Return True if AI decides this email should receive the given tag."""
        if not self.enabled:
            return False

        instruction = ai_instruction or f"Does this email relate to or belong in the '{tag_name}' tag/category?"
        compact_body = compact_for_llm(body, _TAG_BODY_CHARS)
        parsed, _err = self._complete(
            [
                {"role": "system", "content": "You produce strict JSON with a single boolean field 'match'."},
                {
                    "role": "user",
                    "content": (
                        f"Tag name: {tag_name}\n"
                        f"Question: {instruction}\n\n"
                        f"Sender: {sender or 'Unknown'}\n"
                        f"Subject: {subject}\n"
                        f"Body:\n{compact_body}\n\n"
                        "Respond with JSON: {\"match\": true} or {\"match\": false}"
                    ),
                },
            ],
            temperature=0.1,
            timeout=20,
        )
        if not isinstance(parsed, dict):
            return False
        return _parse_bool(parsed.get("match", False))

    def confirm_hide_email(
        self,
        tag_name: str,
        sender: str,
        subject: str,
        body: str,
    ) -> bool:
        """Return True when email is commercial/promotional bulk mail worth hiding."""
        if not self.enabled:
            return False
        compact_body = compact_for_llm(body, _TAG_BODY_CHARS)
        parsed, _err = self._complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You produce strict JSON with a single boolean field 'hide'. "
                        "Answer hide=true only for commercial marketing, promos, or bulk newsletters "
                        "the user would want filtered. Personal, school, transactional, and 1:1 mail "
                        "must be hide=false."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Tag filter: {tag_name}\n"
                        f"Sender: {sender or 'Unknown'}\n"
                        f"Subject: {subject}\n"
                        f"Body:\n{compact_body}\n\n"
                        'Respond with JSON: {"hide": true} or {"hide": false}'
                    ),
                },
            ],
            temperature=0.1,
            timeout=20,
        )
        if not isinstance(parsed, dict):
            return False
        return _parse_bool(parsed.get("hide", False))

    def _email_summary_for_tag(self, email: dict) -> str:
        bullets = email.get("bullet_summary") or []
        summary = " ".join(str(b) for b in bullets if b) or (email.get("preview") or "")
        return compact_for_llm(summary, _TAG_SUMMARY_CHARS)

    def _tag_instruction_lines(self, tags: list[dict]) -> tuple[list[str], dict[str, str], set[str]]:
        tag_lines: list[str] = []
        allowed_lower: dict[str, str] = {}
        allowed: set[str] = set()
        for tag in tags:
            name = str(tag.get("name") or "").strip()
            if not name:
                continue
            allowed.add(name)
            allowed_lower[name.lower()] = name
            instruction = (tag.get("ai_instruction") or "").strip() or f"relates to {name}"
            tag_lines.append(f"- {name}: {instruction}")
        return tag_lines, allowed_lower, allowed

    def classify_emails_for_tags(self, emails: list[dict], tags: list[dict]) -> dict[str, list[str]]:
        """Two-pass tagging: summary first, compact body only when unsure."""
        if not self.enabled or not emails or not tags:
            return {}

        tag_lines, allowed_lower, allowed = self._tag_instruction_lines(tags)
        if not tag_lines:
            return {}

        pass1_blocks: list[str] = []
        for email in emails:
            pass1_blocks.append(
                f"ID: {email['email_id']}\n"
                f"From: {email.get('sender') or 'Unknown'}\n"
                f"Subject: {email.get('subject') or '(no subject)'}\n"
                f"Summary: {self._email_summary_for_tag(email)}"
            )
        pass1_prompt = (
            "For each email, classify every tag as yes, no, or unsure. "
            "Use unsure when the summary is not enough to decide. "
            'Return JSON: {"items": [{"id": "...", "tags": {"Tag Name": "yes|no|unsure"}}]}. '
            "Use exact tag names from the list."
        )
        parsed1, _err = self._complete(
            [
                {"role": "system", "content": "You produce strict JSON."},
                {
                    "role": "user",
                    "content": (
                        f"{pass1_prompt}\n\nTags:\n"
                        + "\n".join(tag_lines)
                        + "\n\nEmails:\n\n"
                        + "\n\n---\n\n".join(pass1_blocks)
                    ),
                },
            ],
            temperature=0.1,
            timeout=30,
        )
        by_id: dict[str, list[str]] = {}
        unsure_emails: list[dict] = []
        unsure_tags_by_id: dict[str, list[str]] = {}
        email_by_id = {e["email_id"]: e for e in emails}
        if isinstance(parsed1, dict):
            entries = parsed1.get("items") or []
            if isinstance(entries, list):
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    eid = str(entry.get("id") or entry.get("email_id") or "")
                    raw_tags = entry.get("tags") or {}
                    if not eid:
                        continue
                    matched: list[str] = []
                    unsure_names: list[str] = []
                    if isinstance(raw_tags, dict):
                        for raw_name, verdict in raw_tags.items():
                            canonical = allowed_lower.get(str(raw_name).strip().lower())
                            if not canonical:
                                continue
                            decision = _parse_tag_verdict(verdict)
                            if decision == "yes":
                                matched.append(canonical)
                            elif decision == "unsure":
                                unsure_names.append(canonical)
                    elif isinstance(raw_tags, list):
                        for raw in raw_tags:
                            canonical = allowed_lower.get(str(raw).strip().lower())
                            if canonical:
                                matched.append(canonical)
                    if matched:
                        by_id[eid] = matched
                    if unsure_names:
                        email_row = email_by_id.get(eid)
                        if email_row:
                            unsure_emails.append(email_row)
                        unsure_tags_by_id[eid] = unsure_names

        if not unsure_emails:
            return by_id

        unsure_tag_lines = [
            line for line in tag_lines
            if any(
                line.startswith(f"- {name}:")
                for names in unsure_tags_by_id.values()
                for name in names
            )
        ]
        pass2_blocks: list[str] = []
        for email in unsure_emails:
            eid = email["email_id"]
            tag_names = unsure_tags_by_id.get(eid) or []
            if not tag_names:
                continue
            body = compact_for_llm(email.get("body") or "", _TAG_BODY_CHARS)
            pass2_blocks.append(
                f"ID: {eid}\n"
                f"From: {email.get('sender') or 'Unknown'}\n"
                f"Subject: {email.get('subject') or '(no subject)'}\n"
                f"Unsure tags: {', '.join(tag_names)}\n"
                f"Body:\n{body}"
            )
        if not pass2_blocks:
            return by_id

        pass2_prompt = (
            "These emails were unsure on pass 1. Read the compact body and assign only the listed unsure tags. "
            "Return JSON: {\"items\": [{\"id\": \"...\", \"tags\": [\"Tag Name\"]}]}. "
            "Only include tags that clearly match."
        )
        parsed2, _err2 = self._complete(
            [
                {"role": "system", "content": "You produce strict JSON."},
                {
                    "role": "user",
                    "content": (
                        f"{pass2_prompt}\n\nTags:\n"
                        + "\n".join(unsure_tag_lines)
                        + "\n\nEmails:\n\n"
                        + "\n\n---\n\n".join(pass2_blocks)
                    ),
                },
            ],
            temperature=0.1,
            timeout=30,
        )
        if isinstance(parsed2, dict):
            entries2 = parsed2.get("items") or []
            if isinstance(entries2, list):
                for entry in entries2:
                    if not isinstance(entry, dict):
                        continue
                    eid = str(entry.get("id") or entry.get("email_id") or "")
                    raw_tags = entry.get("tags") or []
                    if not eid or not isinstance(raw_tags, list):
                        continue
                    existing = set(by_id.get(eid) or [])
                    for raw in raw_tags:
                        canonical = allowed_lower.get(str(raw).strip().lower())
                        if canonical:
                            existing.add(canonical)
                    if existing:
                        by_id[eid] = sorted(existing)
        return by_id

    def identify_action_items(self, emails: list[dict], today: str = "") -> tuple[list[dict], str | None]:
        """Return (items, error_message). error_message is set when the Groq call fails."""
        if not self.enabled or not emails:
            return [], None

        context_parts = []
        for e in emails[:30]:
            bullets = e.get("bullet_summary") or []
            summary = " ".join(bullets) if bullets else (e.get("preview") or "")
            context_parts.append(
                f"ID: {e['email_id']}\n"
                f"Date: {e.get('received_at', 'unknown')}\n"
                f"From: {e.get('sender', '?')}\n"
                f"Subject: {e.get('subject', '?')}\n"
                f"Summary: {summary}"
            )
        context = "\n\n---\n\n".join(context_parts)
        today_line = f"Today's date: {today}\n" if today else ""
        parsed, err = self._complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You are an email triage assistant. Given a list of emails, identify which ones "
                        "require a response or action from the user. Consider recency — emails sent recently "
                        "are more urgent. Return JSON: {\"items\": [{\"email_id\": \"...\", \"reason\": \"...\"}]}"
                    ),
                },
                {
                    "role": "user",
                    "content": f"{today_line}Emails:\n\n{context}\n\nWhich of these emails require a response or action now?",
                },
            ],
            temperature=0.1,
            timeout=40,
        )
        if not isinstance(parsed, dict):
            return [], err
        items = parsed.get("items", [])
        return items if isinstance(items, list) else [], None

    def draft_reply(
        self,
        sender: str,
        subject: str,
        body: str,
        reason: str = "",
    ) -> str | None:
        """Return a short reply draft the user can copy or open via mailto:."""
        if not self.enabled:
            return None

        clipped_body = compact_for_llm(body, 8000)
        context = f"Reason it needs a reply: {reason}\n" if reason else ""
        parsed, _err = self._complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Write a concise, professional email reply draft. "
                        "Return JSON: {\"draft\": \"...\"} with plain text only."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"{context}"
                        f"From: {sender or 'Unknown'}\n"
                        f"Subject: {subject}\n"
                        f"Body:\n{clipped_body}\n\n"
                        "Draft a reply the user can send."
                    ),
                },
            ],
            temperature=0.4,
            timeout=30,
        )
        if not isinstance(parsed, dict):
            return None
        draft = str(parsed.get("draft", "")).strip()
        return draft or None

    def build_inbox_digest(self, emails: list[dict]) -> dict | None:
        """Return headline + bullets for the dashboard brief, or None on failure."""
        if not self.enabled or not emails:
            return None

        context_parts: list[str] = []
        for e in emails[:25]:
            bullets = e.get("bullet_summary") or []
            summary = " ".join(bullets) if bullets else (e.get("preview") or "")
            context_parts.append(
                f"ID: {e['email_id']}\n"
                f"Subject: {e.get('subject', '?')}\n"
                f"From: {e.get('sender', '?')}\n"
                f"Priority: {e.get('priority_score', 0)}\n"
                f"Summary: {summary[:400]}"
            )
        context = "\n\n---\n\n".join(context_parts)
        parsed, _err = self._complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You write inbox briefs for email triage. Return JSON with "
                        "\"headline\" (one short sentence) and \"bullets\" "
                        "(array of up to 6 objects with \"text\" and \"id\" — email ID from context). "
                        "Prioritize deadlines, action items, and urgent mail. No raw URLs in angle brackets."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Summarize this inbox for the user:\n\n{context}",
                },
            ],
            temperature=0.2,
            timeout=35,
        )
        if not isinstance(parsed, dict):
            return None
        headline = str(parsed.get("headline", "")).strip()
        raw_bullets = parsed.get("bullets", [])
        cleaned_bullets: list[dict[str, str]] = []
        if isinstance(raw_bullets, list):
            for item in raw_bullets:
                if isinstance(item, dict):
                    text = str(item.get("text") or item.get("bullet") or "").strip()
                    eid = str(item.get("id") or item.get("email_id") or "").strip()
                    if text:
                        cleaned_bullets.append({"text": text, "email_id": eid})
                elif isinstance(item, str) and item.strip():
                    cleaned_bullets.append({"text": item.strip(), "email_id": ""})
        if headline and cleaned_bullets:
            return {"headline": headline, "bullets": cleaned_bullets[:6]}
        return None

    def analyze_emails_batch(self, emails: list[dict], batch_size: int = 8) -> dict[str, dict]:
        """Return {email_id: {bullets, intent, reason, due_at, tags}} for one Groq batch."""
        if not self.enabled or not emails:
            return {}

        chunk = emails[: max(1, min(batch_size, _MAX_SUMMARY_BATCH))]
        blocks: list[str] = []
        for email in chunk:
            body = compact_for_llm(email.get("body") or "", _BATCH_BODY_CHARS)
            blocks.append(
                f"ID: {email['email_id']}\n"
                f"From: {email.get('sender') or 'Unknown'}\n"
                f"Subject: {email.get('subject') or '(no subject)'}\n"
                f"FromMe: {bool(email.get('from_me'))}\n"
                f"Body:\n{body}"
            )
        prompt = (
            "Analyze each email for inbox triage. Return JSON only: "
            '{"items": [{"id": "...", "line": "one-sentence list summary", "compact": "6-10 word clip", '
            '"bullets": ["..."], "intent": "i_owe|waiting_on_them|deadline|fyi|noise", '
            '"reason": "short why", "due_at": "YYYY-MM-DD or empty", "tags": ["optional tag names"]}]}. '
            f"{_SUMMARY_LINE_HINT} "
            "Up to 3 bullets as distinct facts, dates, or asks. intent=i_owe when the user must reply; waiting_on_them when user sent last; "
            "deadline when a real due date exists; fyi for informational; noise for promos/newsletters. "
            f"{_SUMMARY_TRIAGE_HINT} Use the given ID values exactly."
        )
        parsed, _err = self._complete(
            [
                {"role": "system", "content": "You produce strict JSON for email triage."},
                {
                    "role": "user",
                    "content": f"{prompt}\n\n" + "\n\n---\n\n".join(blocks),
                },
            ],
            timeout=50,
        )
        if not isinstance(parsed, dict):
            return {}
        entries = parsed.get("items") or parsed.get("summaries") or []
        by_id: dict[str, dict] = {}
        if not isinstance(entries, list):
            return by_id
        for entry in entries:
            parsed_entry = parse_analyze_entry(entry)
            if not parsed_entry:
                continue
            eid = str(parsed_entry.pop("id"))
            by_id[eid] = parsed_entry
        return by_id

    def summarize_emails_batch(self, emails: list[dict], batch_size: int = 8) -> dict[str, list[str]]:
        """Return {email_id: bullets} — legacy wrapper around analyze_emails_batch."""
        analyzed = self.analyze_emails_batch(emails, batch_size=batch_size)
        return {eid: data.get("bullets") or [] for eid, data in analyzed.items() if data.get("bullets")}
