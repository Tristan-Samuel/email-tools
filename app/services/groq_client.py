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