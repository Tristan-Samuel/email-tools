from __future__ import annotations

import json
import sqlite3
from pathlib import Path


class EmailStore:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.fts_enabled = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS emails (
                    email_id TEXT PRIMARY KEY,
                    user_email TEXT NOT NULL DEFAULT '',
                    message_id TEXT,
                    source_name TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    sender TEXT,
                    recipient TEXT,
                    cc TEXT,
                    received_at TEXT,
                    body TEXT NOT NULL,
                    preview TEXT NOT NULL,
                    bullet_summary TEXT NOT NULL,
                    category TEXT NOT NULL,
                    priority_score INTEGER NOT NULL,
                    keywords TEXT NOT NULL,
                    search_blob TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    source_account TEXT NOT NULL DEFAULT ''
                )
                """
            )
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(emails)").fetchall()
            }
            if "user_email" not in columns:
                connection.execute("ALTER TABLE emails ADD COLUMN user_email TEXT NOT NULL DEFAULT ''")
            if "source_account" not in columns:
                connection.execute("ALTER TABLE emails ADD COLUMN source_account TEXT NOT NULL DEFAULT ''")

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS imap_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_email TEXT NOT NULL,
                    account_email TEXT NOT NULL,
                    imap_host TEXT NOT NULL,
                    imap_port INTEGER NOT NULL DEFAULT 993,
                    encrypted_password TEXT NOT NULL,
                    last_uid INTEGER NOT NULL DEFAULT 0,
                    last_synced TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_email, account_email)
                )
                """
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_email TEXT PRIMARY KEY,
                    groq_api_key TEXT NOT NULL DEFAULT '',
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            try:
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS email_search USING fts5(
                        email_id UNINDEXED,
                        subject,
                        sender,
                        body,
                        bullet_summary,
                        keywords
                    )
                    """
                )
                self.fts_enabled = True
            except sqlite3.OperationalError:
                self.fts_enabled = False

    def bulk_upsert(self, records: list[dict]) -> int:
        if not records:
            return 0

        with self._connect() as connection:
            for record in records:
                connection.execute(
                    """
                    INSERT INTO emails (
                        email_id,
                        user_email,
                        message_id,
                        source_name,
                        source_account,
                        subject,
                        sender,
                        recipient,
                        cc,
                        received_at,
                        body,
                        preview,
                        bullet_summary,
                        category,
                        priority_score,
                        keywords,
                        search_blob
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(email_id) DO UPDATE SET
                        user_email=excluded.user_email,
                        message_id=excluded.message_id,
                        source_name=excluded.source_name,
                        source_account=excluded.source_account,
                        subject=excluded.subject,
                        sender=excluded.sender,
                        recipient=excluded.recipient,
                        cc=excluded.cc,
                        received_at=excluded.received_at,
                        body=excluded.body,
                        preview=excluded.preview,
                        bullet_summary=excluded.bullet_summary,
                        category=excluded.category,
                        priority_score=excluded.priority_score,
                        keywords=excluded.keywords,
                        search_blob=excluded.search_blob
                    """,
                    (
                        record["email_id"],
                        record["user_email"],
                        record["message_id"],
                        record["source_name"],
                        record.get("source_account", ""),
                        record["subject"],
                        record["sender"],
                        record["recipient"],
                        record["cc"],
                        record["received_at"],
                        record["body"],
                        record["preview"],
                        json.dumps(record["bullet_summary"]),
                        record["category"],
                        record["priority_score"],
                        json.dumps(record["keywords"]),
                        record["search_blob"],
                    ),
                )
                if self.fts_enabled:
                    connection.execute("DELETE FROM email_search WHERE email_id = ?", (record["email_id"],))
                    connection.execute(
                        """
                        INSERT INTO email_search (email_id, subject, sender, body, bullet_summary, keywords)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record["email_id"],
                            record["subject"],
                            record["sender"],
                            record["body"],
                            " ".join(record["bullet_summary"]),
                            " ".join(record["keywords"]),
                        ),
                    )

        return len(records)

    def _deserialize_row(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None

        email = dict(row)
        email["bullet_summary"] = json.loads(email["bullet_summary"])
        email["keywords"] = json.loads(email["keywords"])
        return email

    def list_emails(
        self,
        limit: int = 100,
        category: str | None = None,
        user_email: str | None = None,
        source_account: str | None = None,
    ) -> list[dict]:
        query = "SELECT * FROM emails"
        params: list[object] = []
        conditions: list[str] = []

        if user_email:
            conditions.append("user_email = ?")
            params.append(user_email)
        if source_account:
            conditions.append("source_account = ?")
            params.append(source_account)
        if category:
            conditions.append("category = ?")
            params.append(category)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY priority_score DESC, COALESCE(received_at, created_at) DESC LIMIT ?"
        params.append(limit)

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()

        return [self._deserialize_row(row) for row in rows]

    def search(self, search_term: str, limit: int = 100, user_email: str | None = None, source_account: str | None = None) -> list[dict]:
        with self._connect() as connection:
            acct_clause = " AND emails.source_account = ?" if source_account else ""
            acct_like_clause = " AND source_account = ?" if source_account else ""

            if self.fts_enabled:
                try:
                    if user_email:
                        rows = connection.execute(
                            f"""
                            SELECT emails.*
                            FROM email_search
                            JOIN emails ON emails.email_id = email_search.email_id
                            WHERE email_search MATCH ? AND emails.user_email = ?{acct_clause}
                            ORDER BY priority_score DESC, COALESCE(received_at, created_at) DESC
                            LIMIT ?
                            """,
                            (search_term, user_email, *([source_account] if source_account else []), limit),
                        ).fetchall()
                    else:
                        rows = connection.execute(
                            f"""
                            SELECT emails.*
                            FROM email_search
                            JOIN emails ON emails.email_id = email_search.email_id
                            WHERE email_search MATCH ?{acct_clause}
                            ORDER BY priority_score DESC, COALESCE(received_at, created_at) DESC
                            LIMIT ?
                            """,
                            (search_term, *([source_account] if source_account else []), limit),
                        ).fetchall()
                except sqlite3.OperationalError:
                    wildcard = f"%{search_term}%"
                    if user_email:
                        rows = connection.execute(
                            f"""
                            SELECT * FROM emails
                            WHERE search_blob LIKE ? AND user_email = ?{acct_like_clause}
                            ORDER BY priority_score DESC, COALESCE(received_at, created_at) DESC
                            LIMIT ?
                            """,
                            (wildcard, user_email, *([source_account] if source_account else []), limit),
                        ).fetchall()
                    else:
                        rows = connection.execute(
                            f"""
                            SELECT * FROM emails
                            WHERE search_blob LIKE ?{acct_like_clause}
                            ORDER BY priority_score DESC, COALESCE(received_at, created_at) DESC
                            LIMIT ?
                            """,
                            (wildcard, *([source_account] if source_account else []), limit),
                        ).fetchall()
            else:
                wildcard = f"%{search_term}%"
                if user_email:
                    rows = connection.execute(
                        f"""
                        SELECT * FROM emails
                        WHERE search_blob LIKE ? AND user_email = ?{acct_like_clause}
                        ORDER BY priority_score DESC, COALESCE(received_at, created_at) DESC
                        LIMIT ?
                        """,
                        (wildcard, user_email, *([source_account] if source_account else []), limit),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        f"""
                        SELECT * FROM emails
                        WHERE search_blob LIKE ?{acct_like_clause}
                        ORDER BY priority_score DESC, COALESCE(received_at, created_at) DESC
                        LIMIT ?
                        """,
                        (wildcard, *([source_account] if source_account else []), limit),
                    ).fetchall()

        return [self._deserialize_row(row) for row in rows]

    def get_email(self, email_id: str, user_email: str | None = None) -> dict | None:
        with self._connect() as connection:
            if user_email:
                row = connection.execute(
                    "SELECT * FROM emails WHERE email_id = ? AND user_email = ?",
                    (email_id, user_email),
                ).fetchone()
            else:
                row = connection.execute("SELECT * FROM emails WHERE email_id = ?", (email_id,)).fetchone()
        return self._deserialize_row(row)

    def get_categories(self, user_email: str | None = None, source_account: str | None = None) -> list[dict]:
        with self._connect() as connection:
            conditions: list[str] = []
            params: list[object] = []
            if user_email:
                conditions.append("user_email = ?")
                params.append(user_email)
            if source_account:
                conditions.append("source_account = ?")
                params.append(source_account)
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            rows = connection.execute(
                f"""
                SELECT category, COUNT(*) AS count, MAX(priority_score) AS max_priority
                FROM emails
                {where}
                GROUP BY category
                ORDER BY count DESC, max_priority DESC
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_stats(self, user_email: str | None = None, source_account: str | None = None) -> dict:
        with self._connect() as connection:
            conditions: list[str] = []
            params: list[object] = []
            if user_email:
                conditions.append("user_email = ?")
                params.append(user_email)
            if source_account:
                conditions.append("source_account = ?")
                params.append(source_account)
            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

            total = connection.execute(f"SELECT COUNT(*) FROM emails {where}", params).fetchone()[0]
            urgent = connection.execute(
                f"SELECT COUNT(*) FROM emails {where + (' AND ' if where else 'WHERE ')}priority_score >= 80",
                params,
            ).fetchone()[0]
            categories = connection.execute(
                f"SELECT COUNT(DISTINCT category) FROM emails {where}", params
            ).fetchone()[0]
            latest = connection.execute(
                f"SELECT COALESCE(MAX(received_at), MAX(created_at)) FROM emails {where}", params
            ).fetchone()[0]

        return {
            "total": total,
            "urgent": urgent,
            "categories": categories,
            "latest": latest,
        }

    # ------------------------------------------------------------------
    # IMAP account management
    # ------------------------------------------------------------------

    def save_imap_account(
        self,
        user_email: str,
        account_email: str,
        imap_host: str,
        imap_port: int,
        encrypted_password: str,
    ) -> int:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO imap_accounts (user_email, account_email, imap_host, imap_port, encrypted_password)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_email, account_email) DO UPDATE SET
                    imap_host=excluded.imap_host,
                    imap_port=excluded.imap_port,
                    encrypted_password=excluded.encrypted_password
                """,
                (user_email, account_email, imap_host, imap_port, encrypted_password),
            )
            row = connection.execute(
                "SELECT id FROM imap_accounts WHERE user_email = ? AND account_email = ?",
                (user_email, account_email),
            ).fetchone()
        return row["id"]

    def list_imap_accounts(self, user_email: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM imap_accounts WHERE user_email = ? ORDER BY created_at",
                (user_email,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_imap_account(self, account_id: int, user_email: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM imap_accounts WHERE id = ? AND user_email = ?",
                (account_id, user_email),
            ).fetchone()
        return dict(row) if row else None

    def delete_imap_account(self, account_id: int, user_email: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM imap_accounts WHERE id = ? AND user_email = ?",
                (account_id, user_email),
            )

    def update_imap_last_sync(self, account_id: int, last_uid: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE imap_accounts
                SET last_uid = ?, last_synced = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (last_uid, account_id),
            )

    # ------------------------------------------------------------------
    # User settings (Groq key, etc.)
    # ------------------------------------------------------------------

    def save_setting(self, user_email: str, key: str, value: str) -> None:
        if key == "groq_api_key":
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO user_settings (user_email, groq_api_key, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_email) DO UPDATE SET
                        groq_api_key=excluded.groq_api_key,
                        updated_at=excluded.updated_at
                    """,
                    (user_email, value),
                )

    def get_setting(self, user_email: str, key: str) -> str:
        if key == "groq_api_key":
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT groq_api_key FROM user_settings WHERE user_email = ?",
                    (user_email,),
                ).fetchone()
            return row["groq_api_key"] if row else ""
        return ""