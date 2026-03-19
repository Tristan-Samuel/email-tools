from __future__ import annotations

import json
import os

import requests


class GroqClient:
    def __init__(self, api_key: str, default_model: str):
        self.api_key = api_key.strip()
        self.default_model = default_model
        self.base_url = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def select_max_context_model(self) -> str:
        if not self.enabled:
            return self.default_model

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
            parsed = content if isinstance(content, dict) else json.loads(content)

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
            parsed = content if isinstance(content, dict) else json.loads(content)
            return bool(parsed.get("match", False))
        except (requests.RequestException, KeyError, ValueError, TypeError):
            return False

    def identify_action_items(self, emails: list[dict], today: str = "") -> list[dict]:
        """Return a list of {email_id, subject, sender, reason} for emails needing a response."""
        if not self.enabled or not emails:
            return []

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
            parsed = content if isinstance(content, dict) else json.loads(content)
            return parsed.get("items", [])
        except (requests.RequestException, KeyError, ValueError, TypeError):
            return []