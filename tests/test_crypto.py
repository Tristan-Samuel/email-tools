from __future__ import annotations

from app.services import crypto


def test_decrypt_with_fallback_tries_legacy_key() -> None:
    plaintext = "mailbox-app-password"
    old_key = "legacy-secret"
    new_key = "current-secret"
    token = crypto.encrypt(plaintext, old_key, purpose="imap")

    assert crypto.decrypt(token, new_key, purpose="imap") == ""
    recovered, used = crypto.decrypt_with_fallback(token, [new_key, old_key], purpose="imap")
    assert recovered == plaintext
    assert used == old_key


def test_decrypt_with_fallback_empty_on_total_failure() -> None:
    token = crypto.encrypt("secret", "right-key", purpose="imap")
    recovered, used = crypto.decrypt_with_fallback(token, ["wrong-a", "wrong-b"], purpose="imap")
    assert recovered == ""
    assert used == ""
