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
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(emails)").fetchall()
            }
            if "user_email" not in columns:
                connection.execute("ALTER TABLE emails ADD COLUMN user_email TEXT NOT NULL DEFAULT ''")
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
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(email_id) DO UPDATE SET
                        user_email=excluded.user_email,
                        message_id=excluded.message_id,
                        source_name=excluded.source_name,
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
    ) -> list[dict]:
        query = "SELECT * FROM emails"
        params: list[object] = []

        if user_email:
            query += " WHERE user_email = ?"
            params.append(user_email)

        if category:
            query += " AND category = ?" if user_email else " WHERE category = ?"
            params.append(category)

        query += " ORDER BY priority_score DESC, COALESCE(received_at, created_at) DESC LIMIT ?"
        params.append(limit)

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()

        return [self._deserialize_row(row) for row in rows]

    def search(self, search_term: str, limit: int = 100, user_email: str | None = None) -> list[dict]:
        with self._connect() as connection:
            if self.fts_enabled:
                try:
                    if user_email:
                        rows = connection.execute(
                            """
                            SELECT emails.*
                            FROM email_search
                            JOIN emails ON emails.email_id = email_search.email_id
                            WHERE email_search MATCH ? AND emails.user_email = ?
                            ORDER BY priority_score DESC, COALESCE(received_at, created_at) DESC
                            LIMIT ?
                            """,
                            (search_term, user_email, limit),
                        ).fetchall()
                    else:
                        rows = connection.execute(
                            """
                            SELECT emails.*
                            FROM email_search
                            JOIN emails ON emails.email_id = email_search.email_id
                            WHERE email_search MATCH ?
                            ORDER BY priority_score DESC, COALESCE(received_at, created_at) DESC
                            LIMIT ?
                            """,
                            (search_term, limit),
                        ).fetchall()
                except sqlite3.OperationalError:
                    wildcard = f"%{search_term}%"
                    if user_email:
                        rows = connection.execute(
                            """
                            SELECT * FROM emails
                            WHERE search_blob LIKE ? AND user_email = ?
                            ORDER BY priority_score DESC, COALESCE(received_at, created_at) DESC
                            LIMIT ?
                            """,
                            (wildcard, user_email, limit),
                        ).fetchall()
                    else:
                        rows = connection.execute(
                            """
                            SELECT * FROM emails
                            WHERE search_blob LIKE ?
                            ORDER BY priority_score DESC, COALESCE(received_at, created_at) DESC
                            LIMIT ?
                            """,
                            (wildcard, limit),
                        ).fetchall()
            else:
                wildcard = f"%{search_term}%"
                if user_email:
                    rows = connection.execute(
                        """
                        SELECT * FROM emails
                        WHERE search_blob LIKE ? AND user_email = ?
                        ORDER BY priority_score DESC, COALESCE(received_at, created_at) DESC
                        LIMIT ?
                        """,
                        (wildcard, user_email, limit),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """
                        SELECT * FROM emails
                        WHERE search_blob LIKE ?
                        ORDER BY priority_score DESC, COALESCE(received_at, created_at) DESC
                        LIMIT ?
                        """,
                        (wildcard, limit),
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

    def get_categories(self, user_email: str | None = None) -> list[dict]:
        with self._connect() as connection:
            if user_email:
                rows = connection.execute(
                    """
                    SELECT category, COUNT(*) AS count, MAX(priority_score) AS max_priority
                    FROM emails
                    WHERE user_email = ?
                    GROUP BY category
                    ORDER BY count DESC, max_priority DESC
                    """,
                    (user_email,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT category, COUNT(*) AS count, MAX(priority_score) AS max_priority
                    FROM emails
                    GROUP BY category
                    ORDER BY count DESC, max_priority DESC
                    """
                ).fetchall()

        return [dict(row) for row in rows]

    def get_stats(self, user_email: str | None = None) -> dict:
        with self._connect() as connection:
            if user_email:
                total = connection.execute(
                    "SELECT COUNT(*) FROM emails WHERE user_email = ?",
                    (user_email,),
                ).fetchone()[0]
                urgent = connection.execute(
                    "SELECT COUNT(*) FROM emails WHERE user_email = ? AND priority_score >= 80",
                    (user_email,),
                ).fetchone()[0]
                categories = connection.execute(
                    "SELECT COUNT(DISTINCT category) FROM emails WHERE user_email = ?",
                    (user_email,),
                ).fetchone()[0]
                latest = connection.execute(
                    "SELECT COALESCE(MAX(received_at), MAX(created_at)) FROM emails WHERE user_email = ?",
                    (user_email,),
                ).fetchone()[0]
            else:
                total = connection.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
                urgent = connection.execute("SELECT COUNT(*) FROM emails WHERE priority_score >= 80").fetchone()[0]
                categories = connection.execute("SELECT COUNT(DISTINCT category) FROM emails").fetchone()[0]
                latest = connection.execute(
                    "SELECT COALESCE(MAX(received_at), MAX(created_at)) FROM emails"
                ).fetchone()[0]

        return {
            "total": total,
            "urgent": urgent,
            "categories": categories,
            "latest": latest,
        }