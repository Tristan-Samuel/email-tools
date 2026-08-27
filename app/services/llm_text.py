"""Shared text compaction for Groq prompts — no imports from groq_client or summary."""
from __future__ import annotations

import re

ANGLE_URL_RE = re.compile(r"<(https?://[^>\s]+|mailto:[^>\s]+)>", re.I)
RAW_URL_RE = re.compile(r"(https?://[^\s<>\"']+)", re.I)
LABEL_ANGLE_URL_RE = re.compile(r"([^<\n]+?)\s*<(https?://[^>\s]+)>", re.I)
UTM_PARAM_RE = re.compile(r"[?&]utm_[^&\s]+", re.I)


def compact_for_llm(text: str, limit: int = 800) -> str:
    """Strip URLs and tracking noise before sending text to Groq."""
    if not text:
        return ""
    cleaned = LABEL_ANGLE_URL_RE.sub(lambda m: m.group(1).strip(), text)
    cleaned = ANGLE_URL_RE.sub("", cleaned)
    cleaned = RAW_URL_RE.sub("", cleaned)
    cleaned = UTM_PARAM_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" |")
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(limit - 3, 0)].rstrip() + "..."
