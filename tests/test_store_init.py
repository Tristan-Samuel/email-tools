from __future__ import annotations

import tempfile
from pathlib import Path

from app.services.store import EmailStore


def test_initialize_fresh_db() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        store = EmailStore(db_path)
        store.initialize()

        with store._connect() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            version = connection.execute("PRAGMA user_version").fetchone()[0]

        assert "user_settings" in tables
        assert "emails" in tables
        assert "imap_accounts" in tables
        assert version >= 3
