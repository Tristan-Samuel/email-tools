from __future__ import annotations

import hashlib
import json
import os
import re

import requests


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
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    return bool(value)


class GroqClient:
    def __init__(self, api_key: str, default_model: str):
        self.api_key = api_key.strip()
        self.default_model = default_model
        self.base_url = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
        self._cached_best_model: str | None = None

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

    def select_max_context_model(self) -> str:
        if not self.enabled:
            return self.default_model

        if self._cached_best_model:
            return self._cached_best_model

        try:
            from flask import current_app, has_app_context

            if has_app_context():
                cached = current_app.extensions.get(self._app_model_cache_key())
                if cached:
                    self._cached_best_model = cached
                    return cached
        except Exception:
            pass

        try:
            response = requests.get(
                f"{self.base_url}/models",
                headers=self._headers(),
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            models = payload.get("data", [])
            best = self.default_model
            best_context = -1

            for model in models:
                model_id = model.get("id")
                if not model_id:
                    continue

                context_values = [
                    model.get("context_window"),
                    model.get("max_context_length"),
                    model.get("input_token_limit"),
                    model.get("max_input_tokens"),
                ]
                numeric_values = []
                for value in context_values:
                    if isinstance(value, int):
                        numeric_values.append(value)
                    elif isinstance(value, str) and value.isdigit():
                        numeric_values.append(int(value))
                context = max(numeric_values) if numeric_values else 0
                if context > best_context:
                    best_context = context
                    best = model_id

            self._cached_best_model = best
            try:
                from flask import current_app, has_app_context

                if has_app_context():
                    current_app.extensions[self._app_model_cache_key()] = best
            except Exception:
                pass
            return best
        except requests.RequestException:
            return self.default_model

    def summarize_email(self, sender: str, subject: str, body: str) -> list[str] | None:
        if not self.enabled:
            return None

        model_name = self.select_max_context_model()
        clipped_body = body[:12000]
        prompt = (
            "Summarize this email as concise bullet points for fast triage. "
            "Return JSON only with key \"bullets\" as an array of up to 4 strings. "
            "Prioritize action items, deadlines, risks, and decisions."
        )

        payload = {
            "model": model_name,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
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
        }

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            parsed = _parse_json_content(content)

            bullets = parsed.get("bullets", [])
            cleaned = [str(bullet).strip() for bullet in bullets if str(bullet).strip()]
            return cleaned[:4] if cleaned else None
        except (requests.RequestException, KeyError, ValueError, TypeError):
            return None

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

        payload = {
            "model": self.default_model,
            "temperature": 0.3,
            "messages": [
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
        }

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()
        except (requests.RequestException, KeyError, ValueError, TypeError):
            return None

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
        payload = {
            "model": self.default_model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You produce strict JSON with a single boolean field 'match'."},
                {
                    "role": "user",
                    "content": (
                        f"Tag name: {tag_name}\n"
                        f"Question: {instruction}\n\n"
                        f"Sender: {sender or 'Unknown'}\n"
                        f"Subject: {subject}\n"
                        f"Body (first 3000 chars):\n{body[:3000]}\n\n"
                        "Respond with JSON: {\"match\": true} or {\"match\": false}"
                    ),
                },
            ],
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=20,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = _parse_json_content(content)
            return _parse_bool(parsed.get("match", False))
        except (requests.RequestException, KeyError, ValueError, TypeError):
            return False

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

        payload = {
            "model": self.default_model,
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
            "messages": [
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
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=40,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = _parse_json_content(content)
            return parsed.get("items", []), None
        except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
            return [], str(exc)

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
        payload = {
            "model": self.default_model,
            "temperature": 0.4,
            "response_format": {"type": "json_object"},
            "messages": [
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
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = _parse_json_content(content)
            draft = str(parsed.get("draft", "")).strip()
            return draft or None
        except (requests.RequestException, KeyError, ValueError, TypeError):
            return None

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

        payload = {
            "model": self.default_model,
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
            "messages": [
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
        }
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=35,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = _parse_json_content(content)
            headline = str(parsed.get("headline", "")).strip()
            bullets = parsed.get("bullets", [])
            cleaned = [str(b).strip() for b in bullets if str(b).strip()]
            if headline and cleaned:
                return {"headline": headline, "bullets": cleaned[:6]}
            return None
        except (requests.RequestException, KeyError, ValueError, TypeError):
            return None
