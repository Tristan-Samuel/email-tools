"""User preference keys and helpers stored in user_kv."""
from __future__ import annotations

import json
from typing import Any

DISPLAY_NAME = "display_name"
START_PAGE = "start_page"
FYI_CAP = "fyi_cap"
SNOOZE_DEFAULT_DAYS = "snooze_default_days"
KEYBOARD_SHORTCUTS = "keyboard_shortcuts"
TIMEZONE = "timezone"
DATE_FORMAT = "date_format"
DEFAULT_SYNC_DAYS = "default_sync_days"
DEFAULT_SYNC_MAX = "default_sync_max"
GEMINI_MODEL = "gemini_model"
GROQ_MODEL = "groq_model"
OPEN_IN_PROVIDER = "open_in_provider"
SAVED_AI_PROMPTS = "saved_ai_prompts"
ONBOARDING_DISMISSED = "onboarding_dismissed"
FYI_BRIEF_CACHE = "fyi_brief_cache_v1"

VALID_START_PAGES = ("today", "inbox")
VALID_OPEN_IN = ("auto", "gmail", "outlook", "mailto")
VALID_DATE_FORMATS = ("mdy", "dmy", "iso")

DEFAULT_AI_CHIPS: list[dict[str, str]] = [
    {"label": "Assignments", "prompt": "List assignments I need to get done"},
    {"label": "Waiting on me", "prompt": "What emails are waiting on me to reply?"},
    {"label": "This week", "prompt": "What do I need to handle this week?"},
    {"label": "Find emails", "prompt": "Find emails about "},
]

ALLOWED_GEMINI_MODELS = (
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.6-flash",
)
ALLOWED_GROQ_MODELS = (
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
    "qwen/qwen3.6-27b",
)


def get_pref(store: Any, user_email: str, key: str, default: str = "") -> str:
    return (store.get_kv(user_email, key) or default).strip()


def set_pref(store: Any, user_email: str, key: str, value: str) -> None:
    store.set_kv(user_email, key, value)


def get_json_pref(store: Any, user_email: str, key: str, default: Any) -> Any:
    raw = store.get_kv(user_email, key)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def set_json_pref(store: Any, user_email: str, key: str, value: Any) -> None:
    store.set_kv(user_email, key, json.dumps(value))


def display_name(store: Any, user_email: str) -> str:
    name = get_pref(store, user_email, DISPLAY_NAME)
    if name:
        return name
    local = user_email.split("@")[0] if "@" in user_email else user_email
    return local.replace(".", " ").replace("_", " ").title()


def initials(store: Any, user_email: str) -> str:
    name = display_name(store, user_email)
    parts = [p for p in name.split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if parts:
        return parts[0][:2].upper()
    return (user_email[:2] or "?").upper()


def start_page(store: Any, user_email: str) -> str:
    page = get_pref(store, user_email, START_PAGE, "today").lower()
    return page if page in VALID_START_PAGES else "today"


def keyboard_shortcuts_enabled(store: Any, user_email: str) -> bool:
    return get_pref(store, user_email, KEYBOARD_SHORTCUTS, "1") != "0"


def open_in_provider(store: Any, user_email: str) -> str:
    val = get_pref(store, user_email, OPEN_IN_PROVIDER, "auto").lower()
    return val if val in VALID_OPEN_IN else "auto"


def saved_ai_prompts(store: Any, user_email: str) -> list[dict[str, str]]:
    saved = get_json_pref(store, user_email, SAVED_AI_PROMPTS, [])
    if not isinstance(saved, list):
        return list(DEFAULT_AI_CHIPS)
    cleaned: list[dict[str, str]] = []
    for item in saved:
        if isinstance(item, dict):
            label = str(item.get("label") or "").strip()
            prompt = str(item.get("prompt") or "").strip()
            if label and prompt:
                cleaned.append({"label": label, "prompt": prompt})
    return cleaned or list(DEFAULT_AI_CHIPS)


def snooze_default_days(store: Any, user_email: str) -> int:
    raw = get_pref(store, user_email, SNOOZE_DEFAULT_DAYS, "3")
    try:
        days = int(raw)
    except ValueError:
        days = 3
    return max(1, min(30, days))


def fyi_cap(store: Any, user_email: str) -> int:
    raw = get_pref(store, user_email, FYI_CAP, "12")
    try:
        cap = int(raw)
    except ValueError:
        cap = 12
    return max(3, min(50, cap))
