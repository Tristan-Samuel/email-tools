"""
Symmetric encryption for stored IMAP passwords, Groq keys, and Gemini keys.

Uses Fernet with a key derived from CREDENTIAL_ENCRYPTION_KEY or
SECRET_KEY plus a per-purpose salt so session and credential keys differ.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

_CREDENTIAL_SALT = "email-tools-credential-v1"


def _derive_material(secret_key: str, purpose: str = "") -> bytes:
    material = f"{_CREDENTIAL_SALT}:{purpose}:{secret_key}"
    return hashlib.sha256(material.encode()).digest()


def _make_fernet(secret_key: str, purpose: str = "") -> Fernet:
    raw = _derive_material(secret_key, purpose)
    key = base64.urlsafe_b64encode(raw)
    return Fernet(key)


def encrypt(plaintext: str, secret_key: str, purpose: str = "imap") -> str:
    """Return URL-safe base64 ciphertext string."""
    token = _make_fernet(secret_key, purpose).encrypt(plaintext.encode())
    return token.decode()


def decrypt(ciphertext: str, secret_key: str, purpose: str = "imap") -> str:
    """Return original plaintext, or empty string on failure."""
    if not ciphertext:
        return ""
    try:
        return _make_fernet(secret_key, purpose).decrypt(ciphertext.encode()).decode()
    except Exception:
        return ""


def decrypt_with_fallback(ciphertext: str, keys: list[str], purpose: str = "imap") -> tuple[str, str]:
    """Try each key until one decrypts. Return (plaintext, key_used); both empty on failure."""
    if not ciphertext:
        return "", ""
    seen: set[str] = set()
    for key in keys:
        if not key or key in seen:
            continue
        seen.add(key)
        plain = decrypt(ciphertext, key, purpose)
        if plain:
            return plain, key
    return "", ""
