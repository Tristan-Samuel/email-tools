"""
Symmetric encryption for stored IMAP passwords.

Uses Fernet (AES-128-CBC + HMAC-SHA256) with a key derived from the
Flask SECRET_KEY via SHA-256 so no separate key management is needed.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet


def _make_fernet(secret_key: str) -> Fernet:
    raw = hashlib.sha256(secret_key.encode()).digest()
    key = base64.urlsafe_b64encode(raw)
    return Fernet(key)


def encrypt(plaintext: str, secret_key: str) -> str:
    """Return URL-safe base64 ciphertext string."""
    token = _make_fernet(secret_key).encrypt(plaintext.encode())
    return token.decode()


def decrypt(ciphertext: str, secret_key: str) -> str:
    """Return original plaintext, or empty string on failure."""
    try:
        return _make_fernet(secret_key).decrypt(ciphertext.encode()).decode()
    except Exception:
        return ""
