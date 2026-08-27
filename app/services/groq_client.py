from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable

import requests

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
_TAG_BODY_CHARS = 1200
_JSON_MAX_TOKENS = 800


def _parse_json_content(content: str | dict) -> dict:
    if isinstance(content, dict):
        return content
    text = content.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL | re.I)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


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

    def summarize_email(self, sender: str, subject: str, body: str) -> list[str] | None:
        if not self.enabled:
            return None

        clipped_body = body[:_SINGLE_BODY_CHARS]
        prompt = (
            "Summarize this email as concise bullet points for fast triage. "
            "Return JSON only with key \"bullets\" as an array of up to 4 strings. "
            "Prioritize action items, deadlines, risks, and decisions."
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
        if not isinstance(parsed, dict):
            return None
        bullets = parsed.get("bullets", [])
        cleaned = [str(bullet).strip() for bullet in bullets if str(bullet).strip()]
        return cleaned[:4] if cleaned else None

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
                        "Answer concisely using only the email summaries provided. "
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
                        f"Body (first {_TAG_BODY_CHARS} chars):\n{body[:_TAG_BODY_CHARS]}\n\n"
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

    def classify_emails_for_tags(self, emails: list[dict], tags: list[dict]) -> dict[str, list[str]]:
        """Return {email_id: [tag_name, ...]} for Groq-matched tags in this chunk."""
        if not self.enabled or not emails or not tags:
            return {}

        tag_lines: list[str] = []
        allowed = {str(tag.get("name") or "").strip() for tag in tags if str(tag.get("name") or "").strip()}
        allowed_lower = {name.lower(): name for name in allowed}
        for tag in tags:
            name = str(tag.get("name") or "").strip()
            if not name:
                continue
            instruction = (tag.get("ai_instruction") or "").strip() or f"relates to {name}"
            tag_lines.append(f"- {name}: {instruction}")
        if not tag_lines:
            return {}

        blocks: list[str] = []
        for email in emails:
            bullets = email.get("bullet_summary") or []
            summary = " ".join(str(b) for b in bullets if b) or (email.get("preview") or email.get("body") or "")
            blocks.append(
                f"ID: {email['email_id']}\n"
                f"From: {email.get('sender') or 'Unknown'}\n"
                f"Subject: {email.get('subject') or '(no subject)'}\n"
                f"Summary: {str(summary)[:500]}"
            )
        prompt = (
            "Assign zero or more of the given tags to each email. "
            "Only use the exact tag names listed. "
            'Return JSON: {"items": [{"id": "...", "tags": ["Tag Name"]}]}.'
        )
        parsed, _err = self._complete(
            [
                {"role": "system", "content": "You produce strict JSON."},
                {
                    "role": "user",
                    "content": (
                        f"{prompt}\n\nTags:\n"
                        + "\n".join(tag_lines)
                        + "\n\nEmails:\n\n"
                        + "\n\n---\n\n".join(blocks)
                    ),
                },
            ],
            temperature=0.1,
            timeout=30,
        )
        if not isinstance(parsed, dict):
            return {}
        entries = parsed.get("items") or []
        by_id: dict[str, list[str]] = {}
        if not isinstance(entries, list):
            return {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            eid = str(entry.get("id") or entry.get("email_id") or "")
            raw_tags = entry.get("tags") or []
            if not eid or not isinstance(raw_tags, list):
                continue
            matched: list[str] = []
            seen: set[str] = set()
            for raw in raw_tags:
                canonical = allowed_lower.get(str(raw).strip().lower())
                if canonical and canonical not in seen:
                    seen.add(canonical)
                    matched.append(canonical)
            if matched:
                by_id[eid] = matched
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
            temperature=0.3,
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

        clipped_body = body[:8000]
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
                        "\"headline\" (one short sentence) and \"bullets\" (array of up to 6 strings). "
                        "Prioritize deadlines, action items, and urgent mail. No raw URLs in angle brackets."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Summarize this inbox for the user:\n\n{context}",
                },
            ],
            temperature=0.3,
            timeout=35,
        )
        if not isinstance(parsed, dict):
            return None
        headline = str(parsed.get("headline", "")).strip()
        bullets = parsed.get("bullets", [])
        cleaned = [str(b).strip() for b in bullets if str(b).strip()]
        if headline and cleaned:
            return {"headline": headline, "bullets": cleaned[:6]}
        return None

    def summarize_emails_batch(self, emails: list[dict], batch_size: int = 3) -> dict[str, list[str]]:
        """Return {email_id: bullets} for emails Groq summarized in this batch."""
        if not self.enabled or not emails:
            return {}

        chunk = emails[: max(1, min(batch_size, 3))]
        blocks: list[str] = []
        for email in chunk:
            body = (email.get("body") or "")[:_BATCH_BODY_CHARS]
            blocks.append(
                f"ID: {email['email_id']}\n"
                f"From: {email.get('sender') or 'Unknown'}\n"
                f"Subject: {email.get('subject') or '(no subject)'}\n"
                f"Body:\n{body}"
            )
        prompt = (
            "Summarize each email as concise triage bullets. "
            "Return JSON only: {\"items\": [{\"id\": \"...\", \"bullets\": [\"...\", \"...\"]}]}. "
            "Up to 3 bullets per email. Prioritize actions, deadlines, and decisions. "
            "Use the given ID values exactly."
        )
        parsed, _err = self._complete(
            [
                {"role": "system", "content": "You produce strict JSON."},
                {
                    "role": "user",
                    "content": f"{prompt}\n\n" + "\n\n---\n\n".join(blocks),
                },
            ],
            timeout=45,
        )
        if not isinstance(parsed, dict):
            return {}
        entries = parsed.get("items") or parsed.get("summaries") or []
        by_id: dict[str, list[str]] = {}
        if isinstance(entries, dict):
            for eid, bullets in entries.items():
                cleaned = [str(b).strip() for b in (bullets or []) if str(b).strip()]
                if eid and cleaned:
                    by_id[str(eid)] = cleaned[:4]
            return by_id
        if not isinstance(entries, list):
            return {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            eid = str(entry.get("id") or entry.get("email_id") or "")
            bullets = [str(b).strip() for b in (entry.get("bullets") or []) if str(b).strip()]
            if eid and bullets:
                by_id[eid] = bullets[:4]
        if not by_id and len(entries) == len(chunk):
            for email, entry in zip(chunk, entries):
                if not isinstance(entry, dict):
                    continue
                bullets = [str(b).strip() for b in (entry.get("bullets") or []) if str(b).strip()]
                if bullets:
                    by_id[email["email_id"]] = bullets[:4]
        return by_id
