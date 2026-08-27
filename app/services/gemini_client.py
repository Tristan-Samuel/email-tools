"""Google AI Studio / Gemini API client for email triage and summaries."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from google import genai
from google.genai import types

from .groq_client import (
    _BATCH_BODY_CHARS,
    _JSON_MAX_TOKENS,
    _MAX_SUMMARY_BATCH,
    _SINGLE_BODY_CHARS,
    _SUMMARY_TRIAGE_HINT,
    _TAG_BODY_CHARS,
    _TAG_SUMMARY_CHARS,
    _parse_bool,
    _parse_json_content,
    _parse_tag_verdict,
)
from .llm_text import compact_for_llm
from .token_budget import (
    _ANALYZE_PROMPT_OVERHEAD,
    _SEPARATOR,
    format_analyze_email_block,
)

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"
PREFERRED_GEMINI_MODELS = (
    "gemini-2.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
)
_GEMINI_BODY_CHARS = 6000


def resolve_gemini_model(configured: str) -> str:
    configured = (configured or "").strip()
    if configured:
        return configured
    return DEFAULT_GEMINI_MODEL


def _parse_retry_after(value: str | None) -> float:
    try:
        return max(0.5, min(float(value or ""), 120.0))
    except (TypeError, ValueError):
        return 4.0


def is_rate_limit_error(message: str) -> bool:
    lowered = (message or "").lower()
    return any(
        token in lowered
        for token in ("429", "rate limit", "resource_exhausted", "resource exhausted", "quota")
    )


def is_fatal_gemini_auth_error(message: str) -> bool:
    lowered = (message or "").lower()
    return any(
        token in lowered
        for token in ("401", "403", "invalid api", "api key", "permission denied", "unauthenticated")
    )


def is_gemini_unreachable(message: str) -> bool:
    lowered = (message or "").lower()
    return any(
        token in lowered
        for token in (
            "connection",
            "timed out",
            "timeout",
            "network",
            "name resolution",
            "unavailable",
            "503",
            "502",
        )
    )


def is_tpd_exhausted_error(message: str) -> bool:
    lowered = (message or "").lower()
    return "token" in lowered and any(
        token in lowered for token in ("per day", "daily", "tpd", "tokens per day")
    )


def _usage_total_tokens(response: Any) -> int:
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return 0
    total = getattr(meta, "total_token_count", None)
    if total is not None:
        return int(total)
    prompt = int(getattr(meta, "prompt_token_count", 0) or 0)
    candidates = int(getattr(meta, "candidates_token_count", 0) or 0)
    return prompt + candidates


class GeminiClient:
    def __init__(self, api_key: str, default_model: str):
        self.api_key = api_key.strip()
        self.default_model = resolve_gemini_model(default_model)
        self._client: genai.Client | None = None
        self.last_error: str = ""
        self.last_model_used: str = ""
        self.last_tokens_used: int = 0
        self.cancel_check: Callable[[], bool] | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _models_to_try(self) -> list[str]:
        ordered = [self.default_model, *PREFERRED_GEMINI_MODELS]
        seen: set[str] = set()
        result: list[str] = []
        for model_id in ordered:
            if model_id and model_id not in seen:
                seen.add(model_id)
                result.append(model_id)
        return result

    def _cancelled(self) -> bool:
        fn = self.cancel_check
        return bool(fn and fn())

    def _sleep_interruptible(self, seconds: float) -> bool:
        remaining = max(0.0, seconds)
        while remaining > 0:
            if self._cancelled():
                return True
            step = min(1.0, remaining)
            time.sleep(step)
            remaining -= step
        return self._cancelled()

    def _generate_json(
        self,
        user_content: str,
        *,
        system: str = "You produce strict JSON.",
        temperature: float = 0.2,
        max_output_tokens: int = _JSON_MAX_TOKENS,
        timeout_ms: int = 120_000,
    ) -> tuple[dict | str | None, str | None, int]:
        """Return (parsed_json_or_text, error, tokens_used)."""
        if not self.enabled:
            self.last_error = "Gemini API key is missing."
            return None, self.last_error, 0

        last_err = ""
        retry_wait = 0.0
        for attempt in range(2):
            if self._cancelled():
                self.last_error = "Cancelled."
                return None, self.last_error, 0
            if attempt == 1:
                if retry_wait <= 0:
                    break
                if self._sleep_interruptible(retry_wait):
                    self.last_error = "Cancelled."
                    return None, self.last_error, 0

            for model_name in self._models_to_try():
                if self._cancelled():
                    self.last_error = "Cancelled."
                    return None, self.last_error, 0
                config = types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=0),
                    http_options=types.HttpOptions(timeout=timeout_ms),
                )
                try:
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=user_content,
                        config=config,
                    )
                except Exception as exc:
                    last_err = str(exc)
                    if is_gemini_unreachable(last_err):
                        self.last_error = (
                            "Can't reach Gemini (network or DNS). Local summaries are still available."
                        )
                        return None, self.last_error, 0
                    if is_rate_limit_error(last_err):
                        retry_wait = max(retry_wait, _parse_retry_after(None))
                        continue
                    if "404" in last_err or "not found" in last_err.lower():
                        continue
                    continue

                tokens_used = _usage_total_tokens(response)
                text = (getattr(response, "text", None) or "").strip()
                if not text:
                    last_err = "Gemini returned an empty response."
                    continue

                self.last_model_used = model_name
                self.last_tokens_used = tokens_used
                self.last_error = ""
                try:
                    return _parse_json_content(text), None, tokens_used
                except (ValueError, TypeError):
                    last_err = "Gemini returned invalid JSON."
                    continue

        self.last_error = last_err or "Gemini request failed."
        return None, self.last_error, 0

    def _parse_analyze_entries(self, parsed: dict) -> dict[str, dict]:
        entries = parsed.get("items") or parsed.get("summaries") or []
        by_id: dict[str, dict] = {}
        if not isinstance(entries, list):
            return by_id
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            eid = str(entry.get("id") or entry.get("email_id") or "")
            if not eid:
                continue
            bullets = [str(b).strip() for b in (entry.get("bullets") or []) if str(b).strip()]
            intent = str(entry.get("intent") or "fyi").strip().lower()
            if intent not in ("i_owe", "waiting_on_them", "deadline", "fyi", "noise"):
                intent = "fyi"
            reason = str(entry.get("reason") or "").strip()
            due_raw = str(entry.get("due_at") or "").strip()
            due_at = due_raw[:10] if due_raw and due_raw.lower() not in ("", "null", "none") else None
            raw_tags = entry.get("tags") or []
            tags = [str(t).strip() for t in raw_tags if str(t).strip()] if isinstance(raw_tags, list) else []
            by_id[eid] = {
                "bullets": bullets[:4] if bullets else [],
                "intent": intent,
                "reason": reason,
                "due_at": due_at,
                "tags": tags,
            }
        return by_id

    def analyze_emails_batch(
        self,
        emails: list[dict],
        *,
        blocks: list[str] | None = None,
        batch_size: int = _MAX_SUMMARY_BATCH,
    ) -> dict[str, dict]:
        """Analyze a pre-packed batch (or up to batch_size emails with compact bodies)."""
        if not self.enabled or not emails:
            return {}

        if blocks is None:
            chunk = emails[: max(1, min(batch_size, _MAX_SUMMARY_BATCH))]
            blocks = [format_analyze_email_block(e, _BATCH_BODY_CHARS) for e in chunk]
            emails = chunk

        prompt = (
            f"{_ANALYZE_PROMPT_OVERHEAD} {_SUMMARY_TRIAGE_HINT} "
            "Emails:\n\n" + _SEPARATOR.join(blocks)
        )
        max_out = min(16_384, max(_JSON_MAX_TOKENS, len(emails) * 120))
        parsed, _err, _tokens = self._generate_json(
            prompt,
            system="You produce strict JSON for email triage.",
            temperature=0.2,
            max_output_tokens=max_out,
            timeout_ms=180_000,
        )
        if not isinstance(parsed, dict):
            return {}
        return self._parse_analyze_entries(parsed)

    def summarize_email(self, sender: str, subject: str, body: str) -> list[str] | None:
        if not self.enabled:
            return None
        clipped_body = compact_for_llm(body, _SINGLE_BODY_CHARS)
        prompt = (
            "Summarize this email as concise bullet points for fast triage. "
            'Return JSON only with key "bullets" as an array of up to 4 strings. '
            f"{_SUMMARY_TRIAGE_HINT}"
        )
        parsed, _err, _tokens = self._generate_json(
            (
                f"{prompt}\n\n"
                f"Sender: {sender or 'Unknown sender'}\n"
                f"Subject: {subject}\n"
                f"Body:\n{clipped_body}"
            ),
            timeout_ms=60_000,
        )
        if not isinstance(parsed, dict):
            return None
        bullets = parsed.get("bullets", [])
        cleaned = [str(bullet).strip() for bullet in bullets if str(bullet).strip()]
        return cleaned[:4] if cleaned else None

    def answer_about_emails(self, question: str, emails: list[dict]) -> str | None:
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
        parsed, _err, _tokens = self._generate_json(
            f"My emails:\n\n{context}\n\nQuestion: {question}",
            system=(
                "You are a helpful email assistant. Answer concisely using only the email summaries provided. "
                "If you can't answer from the emails, say so briefly. Return plain text only as JSON "
                '{"answer": "..."}.'
            ),
            timeout_ms=60_000,
        )
        if isinstance(parsed, dict):
            answer = str(parsed.get("answer", "")).strip()
            return answer or None
        return parsed if isinstance(parsed, str) and parsed else None

    def classify_email_for_tag(
        self,
        tag_name: str,
        ai_instruction: str,
        sender: str,
        subject: str,
        body: str,
    ) -> bool:
        if not self.enabled:
            return False
        instruction = ai_instruction or f"Does this email relate to or belong in the '{tag_name}' tag/category?"
        compact_body = compact_for_llm(body, _TAG_BODY_CHARS)
        parsed, _err, _tokens = self._generate_json(
            (
                f"Tag name: {tag_name}\n"
                f"Question: {instruction}\n\n"
                f"Sender: {sender or 'Unknown'}\n"
                f"Subject: {subject}\n"
                f"Body:\n{compact_body}\n\n"
                'Respond with JSON: {"match": true} or {"match": false}'
            ),
            system="You produce strict JSON with a single boolean field 'match'.",
            temperature=0.1,
            timeout_ms=40_000,
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
        if not self.enabled:
            return False
        compact_body = compact_for_llm(body, _TAG_BODY_CHARS)
        parsed, _err, _tokens = self._generate_json(
            (
                f"Tag filter: {tag_name}\n"
                f"Sender: {sender or 'Unknown'}\n"
                f"Subject: {subject}\n"
                f"Body:\n{compact_body}\n\n"
                'Respond with JSON: {"hide": true} or {"hide": false}'
            ),
            system=(
                "You produce strict JSON with a single boolean field 'hide'. "
                "Answer hide=true only for commercial marketing, promos, or bulk newsletters "
                "the user would want filtered. Personal, school, transactional, and 1:1 mail "
                "must be hide=false."
            ),
            temperature=0.1,
            timeout_ms=40_000,
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
        parsed1, _err, _tokens = self._generate_json(
            (
                f"{pass1_prompt}\n\nTags:\n"
                + "\n".join(tag_lines)
                + "\n\nEmails:\n\n"
                + "\n\n---\n\n".join(pass1_blocks)
            ),
            system="You produce strict JSON.",
            temperature=0.1,
            timeout_ms=90_000,
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
            line
            for line in tag_lines
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
            'Return JSON: {"items": [{"id": "...", "tags": ["Tag Name"]}]}. '
            "Only include tags that clearly match."
        )
        parsed2, _err2, _tokens2 = self._generate_json(
            (
                f"{pass2_prompt}\n\nTags:\n"
                + "\n".join(unsure_tag_lines)
                + "\n\nEmails:\n\n"
                + "\n\n---\n\n".join(pass2_blocks)
            ),
            system="You produce strict JSON.",
            temperature=0.1,
            timeout_ms=90_000,
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
        parsed, err, _tokens = self._generate_json(
            f"{today_line}Emails:\n\n{context}\n\nWhich of these emails require a response or action now?",
            system=(
                "You are an email triage assistant. Return JSON: "
                '{"items": [{"email_id": "...", "reason": "..."}]}'
            ),
            temperature=0.1,
            timeout_ms=90_000,
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
        if not self.enabled:
            return None
        clipped_body = compact_for_llm(body, 8000)
        context = f"Reason it needs a reply: {reason}\n" if reason else ""
        parsed, _err, _tokens = self._generate_json(
            (
                f"{context}"
                f"From: {sender or 'Unknown'}\n"
                f"Subject: {subject}\n"
                f"Body:\n{clipped_body}\n\n"
                "Draft a reply the user can send."
            ),
            system=(
                'Write a concise, professional email reply draft. '
                'Return JSON: {"draft": "..."} with plain text only.'
            ),
            temperature=0.4,
            timeout_ms=60_000,
        )
        if not isinstance(parsed, dict):
            return None
        draft = str(parsed.get("draft", "")).strip()
        return draft or None

    def build_inbox_digest(self, emails: list[dict]) -> dict | None:
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
        parsed, _err, _tokens = self._generate_json(
            f"Summarize this inbox for the user:\n\n{context}",
            system=(
                "You write inbox briefs for email triage. Return JSON with "
                '"headline" (one short sentence) and "bullets" '
                '(array of up to 6 objects with "text" and "id" — email ID from context). '
                "Prioritize deadlines, action items, and urgent mail. No raw URLs in angle brackets."
            ),
            temperature=0.2,
            timeout_ms=90_000,
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

    def summarize_emails_batch(self, emails: list[dict], batch_size: int = 8) -> dict[str, list[str]]:
        analyzed = self.analyze_emails_batch(emails, batch_size=batch_size)
        return {eid: data.get("bullets") or [] for eid, data in analyzed.items() if data.get("bullets")}
