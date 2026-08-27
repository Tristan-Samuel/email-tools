"""Token counting and greedy batch packing for Gemini email analysis."""
from __future__ import annotations

import datetime as dt
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from .llm_text import compact_for_llm

if TYPE_CHECKING:
    from .store import EmailStore

_PACIFIC = ZoneInfo("America/Los_Angeles")
_ANALYZE_PROMPT_OVERHEAD = (
    "Analyze each email for inbox triage. Return JSON only: "
    '{"items": [{"id": "...", "bullets": ["..."], "intent": "i_owe|waiting_on_them|deadline|fyi|noise", '
    '"reason": "short why", "due_at": "YYYY-MM-DD or empty", "tags": ["optional tag names"]}]}. '
    "Up to 3 bullets per email. intent=i_owe when the user must reply; waiting_on_them when user sent last; "
    "deadline when a real due date exists; fyi for informational; noise for promos/newsletters. "
    "Use the given ID values exactly."
)
_SEPARATOR = "\n\n---\n\n"


@dataclass(frozen=True)
class BudgetLimits:
    """Gemini free-tier style limits (override via env to match AI Studio dashboard)."""

    rpm: int = 15
    tpm: int = 250_000
    tpd: int = 1_500_000
    context_window: int = 1_048_576
    output_reserve: int = 16_384
    max_output_tokens: int = 65_536
    tokens_per_email_output: int = 120
    max_emails_per_batch: int = 130
    body_chars: int = 6000
    tpm_safety: float = 0.7

    @classmethod
    def from_env(cls) -> BudgetLimits:
        return cls(
            rpm=int(os.environ.get("GEMINI_RPM", "15")),
            tpm=int(os.environ.get("GEMINI_TPM", "250000")),
            tpd=int(os.environ.get("GEMINI_TPD", "1500000")),
            context_window=int(os.environ.get("GEMINI_CONTEXT_WINDOW", "1048576")),
        )

    def max_input_tokens(self, remaining_tpd: int) -> int:
        return min(
            int(self.tpm * self.tpm_safety),
            self.context_window - self.output_reserve,
            max(0, remaining_tpd),
        )

    def max_output_budget(self) -> int:
        return min(16_384, self.max_output_tokens // 4)


class TokenCounter:
    """Hybrid local Gemini tokenizer with char/4 fallback."""

    def __init__(self, model_name: str, api_client: Any | None = None) -> None:
        self.model_name = model_name
        self._api_client = api_client
        self._local: Any | None = None
        self._init_local()

    def _init_local(self) -> None:
        try:
            from google.genai import local_tokenizer

            self._local = local_tokenizer.LocalTokenizer(model_name=self.model_name)
        except Exception:
            self._local = None

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self._local is not None:
            try:
                result = self._local.count_tokens(text)
                total = getattr(result, "total_tokens", None)
                if total is not None:
                    return int(total)
            except Exception:
                pass
        return max(1, len(text) // 4)

    def preflight_count(self, text: str) -> int | None:
        """Optional one-shot CountTokens API on a packed prompt."""
        if self._api_client is None:
            return None
        try:
            response = self._api_client.models.count_tokens(
                model=self.model_name,
                contents=text,
            )
            total = getattr(response, "total_tokens", None)
            return int(total) if total is not None else None
        except Exception:
            return None


def pacific_today() -> str:
    return dt.datetime.now(_PACIFIC).strftime("%Y-%m-%d")


def format_analyze_email_block(email: dict, body_chars: int) -> str:
    body = compact_for_llm(email.get("body") or "", body_chars)
    return (
        f"ID: {email['email_id']}\n"
        f"From: {email.get('sender') or 'Unknown'}\n"
        f"Subject: {email.get('subject') or '(no subject)'}\n"
        f"FromMe: {bool(email.get('from_me'))}\n"
        f"Body:\n{body}"
    )


def pack_email_batch(
    emails: list[dict],
    counter: TokenCounter,
    limits: BudgetLimits,
    remaining_tpd: int,
    *,
    system_tokens: int = 80,
) -> tuple[list[dict], list[str]]:
    """Greedy-pack as many emails as fit under TPM, context, TPD, and output budgets."""
    if not emails:
        return [], []

    max_input = limits.max_input_tokens(remaining_tpd)
    prompt_base = counter.count(_ANALYZE_PROMPT_OVERHEAD) + system_tokens
    sep_tokens = counter.count(_SEPARATOR)

    packed: list[dict] = []
    blocks: list[str] = []
    input_used = prompt_base

    for email in emails:
        body_chars = limits.body_chars
        block = format_analyze_email_block(email, body_chars)
        block_tokens = counter.count(block)

        if not packed and block_tokens + input_used > max_input:
            while body_chars > 400 and block_tokens + input_used > max_input:
                body_chars = max(400, body_chars // 2)
                block = format_analyze_email_block(email, body_chars)
                block_tokens = counter.count(block)

        next_count = len(packed) + 1
        output_budget = next_count * limits.tokens_per_email_output
        if output_budget > limits.max_output_budget():
            break

        extra = block_tokens + (sep_tokens if packed else 0)
        if packed and input_used + extra > max_input:
            break
        if not packed and input_used + block_tokens > max_input:
            packed.append(email)
            blocks.append(block)
            break
        if len(packed) >= limits.max_emails_per_batch:
            break

        packed.append(email)
        blocks.append(block)
        input_used += extra

    return packed, blocks


def shrink_pack_for_preflight(
    packed: list[dict],
    blocks: list[str],
    counter: TokenCounter,
    limits: BudgetLimits,
    remaining_tpd: int,
    *,
    system_tokens: int = 80,
) -> tuple[list[dict], list[str]]:
    """Drop tail emails until optional CountTokens preflight fits."""
    api_count = counter.preflight_count(
        _ANALYZE_PROMPT_OVERHEAD + _SEPARATOR.join(blocks)
    )
    if api_count is None:
        return packed, blocks

    max_input = limits.max_input_tokens(remaining_tpd)
    while packed and api_count > max_input:
        packed = packed[:-1]
        blocks = blocks[:-1]
        if not blocks:
            break
        api_count = counter.preflight_count(
            _ANALYZE_PROMPT_OVERHEAD + _SEPARATOR.join(blocks)
        )
        if api_count is None:
            break
    return packed, blocks


class GeminiQuotaTracker:
    """RPM pacing and per-day token usage persisted in user_kv."""

    def __init__(self, store: EmailStore, user_email: str, limits: BudgetLimits) -> None:
        self.store = store
        self.user_email = user_email
        self.limits = limits
        self._last_request_mono: float = 0.0

    def _tpd_key(self) -> str:
        return f"gemini_tpd_{pacific_today()}"

    def tokens_used_today(self) -> int:
        raw = self.store.get_kv(self.user_email, self._tpd_key())
        try:
            return int(raw or "0")
        except ValueError:
            return 0

    def remaining_tpd(self) -> int:
        return max(0, self.limits.tpd - self.tokens_used_today())

    def tpd_exhausted(self, min_tokens: int = 500) -> bool:
        return self.remaining_tpd() < min_tokens

    def record_tokens(self, total: int) -> None:
        if total <= 0:
            return
        used = self.tokens_used_today() + total
        self.store.set_kv(self.user_email, self._tpd_key(), str(used))

    def wait_for_rpm_slot(self) -> None:
        if self.limits.rpm <= 0:
            return
        min_interval = 60.0 / self.limits.rpm
        if self._last_request_mono <= 0:
            return
        elapsed = time.monotonic() - self._last_request_mono
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

    def mark_request_started(self) -> None:
        self._last_request_mono = time.monotonic()
