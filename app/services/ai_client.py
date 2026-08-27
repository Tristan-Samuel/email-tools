"""Unified AI client: Gemini primary, Groq fallback."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .gemini_client import (
    DEFAULT_GEMINI_MODEL,
    GeminiClient,
    is_fatal_gemini_auth_error,
    is_gemini_unreachable,
    is_rate_limit_error as is_gemini_rate_limit_error,
    is_tpd_exhausted_error,
)
from .groq_client import (
    GroqClient,
    is_fatal_groq_auth_error,
    is_groq_unreachable,
    is_rate_limit_error as is_groq_rate_limit_error,
)
from .token_budget import (
    BudgetLimits,
    GeminiQuotaTracker,
    TokenCounter,
    pack_email_batch,
    shrink_pack_for_preflight,
)


class AiClient:
    """Facade over Gemini (primary) and Groq (fallback)."""

    def __init__(self, gemini: GeminiClient, groq: GroqClient):
        self._gemini = gemini
        self._groq = groq
        self._gemini_fallback = False
        self.last_error: str = ""
        self.last_model_used: str = ""
        self.last_provider: str = ""
        self.cancel_check: Callable[[], bool] | None = None

    @property
    def enabled(self) -> bool:
        return self._gemini.enabled or self._groq.enabled

    @property
    def gemini_enabled(self) -> bool:
        return self._gemini.enabled and not self._gemini_fallback

    @property
    def groq_enabled(self) -> bool:
        return self._groq.enabled

    def _sync_cancel(self) -> None:
        check = self.cancel_check
        self._gemini.cancel_check = check
        self._groq.cancel_check = check

    def _gemini_failed(self, err: str) -> bool:
        if not err:
            return False
        if is_fatal_gemini_auth_error(err) or is_gemini_unreachable(err):
            return True
        if is_gemini_rate_limit_error(err) or is_tpd_exhausted_error(err):
            return True
        return False

    def disable_gemini_for_job(self, reason: str) -> None:
        self._gemini_fallback = True
        self.last_error = reason

    def select_max_context_model(self) -> str:
        self._sync_cancel()
        if self.gemini_enabled:
            self.last_provider = "gemini"
            self.last_model_used = self._gemini.default_model
            return self._gemini.default_model
        if self._groq.enabled:
            self.last_provider = "groq"
            model = self._groq.select_max_context_model()
            self.last_model_used = model
            return model
        return ""

    def analyze_emails_batch(
        self,
        emails: list[dict],
        batch_size: int = 8,
        *,
        blocks: list[str] | None = None,
    ) -> dict[str, dict]:
        self._sync_cancel()
        if self.gemini_enabled:
            result = self._gemini.analyze_emails_batch(emails, blocks=blocks, batch_size=batch_size)
            self.last_error = self._gemini.last_error
            self.last_model_used = self._gemini.last_model_used
            self.last_provider = "gemini"
            if result or not self._gemini_failed(self._gemini.last_error):
                return result
            self.disable_gemini_for_job(self._gemini.last_error or "Gemini batch failed.")
        if self._groq.enabled:
            result = self._groq.analyze_emails_batch(emails, batch_size=batch_size)
            self.last_error = self._groq.last_error
            self.last_model_used = self._groq.last_model_used
            self.last_provider = "groq"
            return result
        self.last_error = "No AI provider configured."
        return {}

    def analyze_with_token_packing(
        self,
        emails: list[dict],
        store: Any,
        user_email: str,
        limits: BudgetLimits | None = None,
    ) -> list[tuple[list[dict], dict[str, dict], int]]:
        """Yield-style batches: list of (chunk, results, tokens_used) for Gemini packing."""
        self._sync_cancel()
        if not self.gemini_enabled:
            return []

        limits = limits or BudgetLimits.from_env()
        tracker = GeminiQuotaTracker(store, user_email, limits)
        counter = TokenCounter(
            self._gemini.default_model,
            api_client=self._gemini.client if self._gemini.enabled else None,
        )
        batches: list[tuple[list[dict], dict[str, dict], int]] = []
        remaining = list(emails)

        while remaining:
            if tracker.tpd_exhausted():
                self.disable_gemini_for_job("Gemini daily token budget reached.")
                break

            packed, blocks = pack_email_batch(remaining, counter, limits, tracker.remaining_tpd())
            if not packed:
                break
            packed, blocks = shrink_pack_for_preflight(
                packed, blocks, counter, limits, tracker.remaining_tpd()
            )
            if not packed:
                break

            tracker.wait_for_rpm_slot()
            tracker.mark_request_started()
            results = self._gemini.analyze_emails_batch(packed, blocks=blocks)
            tokens = self._gemini.last_tokens_used
            tracker.record_tokens(tokens)
            self.last_error = self._gemini.last_error
            self.last_model_used = self._gemini.last_model_used
            self.last_provider = "gemini"

            if not results and self._gemini_failed(self._gemini.last_error):
                if len(packed) > 1:
                    half = len(packed) // 2
                    packed = packed[:half]
                    blocks = blocks[:half]
                    tracker.wait_for_rpm_slot()
                    tracker.mark_request_started()
                    results = self._gemini.analyze_emails_batch(packed, blocks=blocks)
                    tokens = self._gemini.last_tokens_used
                    tracker.record_tokens(tokens)
                if not results and self._gemini_failed(self._gemini.last_error):
                    self.disable_gemini_for_job(self._gemini.last_error or "Gemini failed.")
                    break

            batches.append((packed, results, tokens))
            remaining = remaining[len(packed) :]

        return batches

    def summarize_email(self, sender: str, subject: str, body: str) -> list[str] | None:
        self._sync_cancel()
        if self.gemini_enabled:
            bullets = self._gemini.summarize_email(sender, subject, body)
            if bullets:
                self.last_provider = "gemini"
                self.last_model_used = self._gemini.last_model_used
                return bullets
            if self._gemini_failed(self._gemini.last_error):
                self.disable_gemini_for_job(self._gemini.last_error)
        if self._groq.enabled:
            bullets = self._groq.summarize_email(sender, subject, body)
            self.last_provider = "groq"
            self.last_model_used = self._groq.last_model_used
            self.last_error = self._groq.last_error
            return bullets
        return None

    def answer_about_emails(self, question: str, emails: list[dict]) -> str | None:
        self._sync_cancel()
        if self.gemini_enabled:
            answer = self._gemini.answer_about_emails(question, emails)
            if answer:
                self.last_provider = "gemini"
                return answer
            if self._gemini_failed(self._gemini.last_error):
                self.disable_gemini_for_job(self._gemini.last_error)
        if self._groq.enabled:
            self.last_provider = "groq"
            return self._groq.answer_about_emails(question, emails)
        return None

    def classify_email_for_tag(
        self,
        tag_name: str,
        ai_instruction: str,
        sender: str,
        subject: str,
        body: str,
    ) -> bool:
        self._sync_cancel()
        if self.gemini_enabled:
            match = self._gemini.classify_email_for_tag(
                tag_name, ai_instruction, sender, subject, body
            )
            if self._gemini.last_error and self._gemini_failed(self._gemini.last_error):
                self.disable_gemini_for_job(self._gemini.last_error)
            elif not self._gemini.last_error or match:
                self.last_provider = "gemini"
                return match
        if self._groq.enabled:
            self.last_provider = "groq"
            return self._groq.classify_email_for_tag(
                tag_name, ai_instruction, sender, subject, body
            )
        return False

    def confirm_hide_email(
        self,
        tag_name: str,
        sender: str,
        subject: str,
        body: str,
    ) -> bool:
        self._sync_cancel()
        if self.gemini_enabled:
            hide = self._gemini.confirm_hide_email(tag_name, sender, subject, body)
            if self._gemini.last_error and self._gemini_failed(self._gemini.last_error):
                self.disable_gemini_for_job(self._gemini.last_error)
            else:
                self.last_provider = "gemini"
                return hide
        if self._groq.enabled:
            self.last_provider = "groq"
            return self._groq.confirm_hide_email(tag_name, sender, subject, body)
        return False

    def classify_emails_for_tags(self, emails: list[dict], tags: list[dict]) -> dict[str, list[str]]:
        self._sync_cancel()
        if self.gemini_enabled:
            result = self._gemini.classify_emails_for_tags(emails, tags)
            if result or not self._gemini_failed(self._gemini.last_error):
                self.last_provider = "gemini"
                return result
            self.disable_gemini_for_job(self._gemini.last_error or "Gemini tagging failed.")
        if self._groq.enabled:
            self.last_provider = "groq"
            return self._groq.classify_emails_for_tags(emails, tags)
        return {}

    def identify_action_items(self, emails: list[dict], today: str = "") -> tuple[list[dict], str | None]:
        self._sync_cancel()
        if self.gemini_enabled:
            items, err = self._gemini.identify_action_items(emails, today=today)
            if items or not self._gemini_failed(err or self._gemini.last_error):
                self.last_provider = "gemini"
                return items, err
            self.disable_gemini_for_job(err or self._gemini.last_error or "Gemini failed.")
        if self._groq.enabled:
            self.last_provider = "groq"
            return self._groq.identify_action_items(emails, today=today)
        return [], None

    def draft_reply(
        self,
        sender: str,
        subject: str,
        body: str,
        reason: str = "",
    ) -> str | None:
        self._sync_cancel()
        if self.gemini_enabled:
            draft = self._gemini.draft_reply(sender, subject, body, reason=reason)
            if draft:
                self.last_provider = "gemini"
                return draft
            if self._gemini_failed(self._gemini.last_error):
                self.disable_gemini_for_job(self._gemini.last_error)
        if self._groq.enabled:
            self.last_provider = "groq"
            return self._groq.draft_reply(sender, subject, body, reason=reason)
        return None

    def build_inbox_digest(self, emails: list[dict]) -> dict | None:
        self._sync_cancel()
        if self.gemini_enabled:
            digest = self._gemini.build_inbox_digest(emails)
            if digest:
                self.last_provider = "gemini"
                return digest
            if self._gemini_failed(self._gemini.last_error):
                self.disable_gemini_for_job(self._gemini.last_error)
        if self._groq.enabled:
            self.last_provider = "groq"
            return self._groq.build_inbox_digest(emails)
        return None

    def summarize_emails_batch(self, emails: list[dict], batch_size: int = 8) -> dict[str, list[str]]:
        analyzed = self.analyze_emails_batch(emails, batch_size=batch_size)
        return {eid: data.get("bullets") or [] for eid, data in analyzed.items() if data.get("bullets")}


def is_rate_limit_error(message: str) -> bool:
    return is_gemini_rate_limit_error(message) or is_groq_rate_limit_error(message)


def is_fatal_auth_error(message: str) -> bool:
    return is_fatal_gemini_auth_error(message) or is_fatal_groq_auth_error(message)


def is_unreachable(message: str) -> bool:
    return is_gemini_unreachable(message) or is_groq_unreachable(message)
