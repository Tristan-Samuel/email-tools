from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path


class EmailStore:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.fts_enabled = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _table_columns(self, connection: sqlite3.Connection, table: str) -> set[str]:
        try:
            return {row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
        except sqlite3.OperationalError:
            return set()

    def _migrate_v1(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_email TEXT PRIMARY KEY,
                groq_api_key TEXT NOT NULL DEFAULT '',
                app_password_hash TEXT NOT NULL DEFAULT '',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        settings_cols = self._table_columns(connection, "user_settings")
        if settings_cols and "app_password_hash" not in settings_cols:
            connection.execute(
                "ALTER TABLE user_settings ADD COLUMN app_password_hash TEXT NOT NULL DEFAULT ''"
            )

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
                source_account TEXT NOT NULL DEFAULT '',
                ai_analyzed INTEGER NOT NULL DEFAULT 0,
                is_hidden INTEGER NOT NULL DEFAULT 0,
                is_read INTEGER NOT NULL DEFAULT 0,
                is_mailing_list INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        email_cols = self._table_columns(connection, "emails")
        for col, ddl in (
            ("user_email", "ALTER TABLE emails ADD COLUMN user_email TEXT NOT NULL DEFAULT ''"),
            ("source_account", "ALTER TABLE emails ADD COLUMN source_account TEXT NOT NULL DEFAULT ''"),
            ("ai_analyzed", "ALTER TABLE emails ADD COLUMN ai_analyzed INTEGER NOT NULL DEFAULT 0"),
            ("is_hidden", "ALTER TABLE emails ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0"),
            ("is_read", "ALTER TABLE emails ADD COLUMN is_read INTEGER NOT NULL DEFAULT 0"),
            ("is_mailing_list", "ALTER TABLE emails ADD COLUMN is_mailing_list INTEGER NOT NULL DEFAULT 0"),
        ):
            if email_cols and col not in email_cols:
                connection.execute(ddl)

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
            CREATE TABLE IF NOT EXISTS user_tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                name TEXT NOT NULL,
                color TEXT NOT NULL DEFAULT '#888888',
                use_ai INTEGER NOT NULL DEFAULT 0,
                ai_instruction TEXT NOT NULL DEFAULT '',
                hide_matching INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_email, name)
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS tag_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_id INTEGER NOT NULL REFERENCES user_tags(id) ON DELETE CASCADE,
                field TEXT NOT NULL,
                operator TEXT NOT NULL,
                value TEXT NOT NULL
            )
            """
        )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS email_tags (
                email_id TEXT NOT NULL,
                tag_id INTEGER NOT NULL REFERENCES user_tags(id) ON DELETE CASCADE,
                PRIMARY KEY(email_id, tag_id)
            )
            """
        )

        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_emails_user_received ON emails(user_email, received_at)"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_email_tags_tag ON email_tags(tag_id)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_imap_accounts_user ON imap_accounts(user_email)"
        )

        try:
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS email_search USING fts5(
                    email_id UNINDEXED,
                    subject,
                    sender,
                    recipient,
                    body,
                    bullet_summary,
                    keywords,
                    category
                )
                """
            )
            self.fts_enabled = True
        except sqlite3.OperationalError:
            self.fts_enabled = False

    def _migrate_v2(self, connection: sqlite3.Connection) -> None:
        """IMAP UIDVALIDITY and backfill cursor for incremental sync."""
        cols = self._table_columns(connection, "imap_accounts")
        if cols and "uidvalidity" not in cols:
            connection.execute(
                "ALTER TABLE imap_accounts ADD COLUMN uidvalidity INTEGER NOT NULL DEFAULT 0"
            )
        if cols and "backfill_uid" not in cols:
            connection.execute(
                "ALTER TABLE imap_accounts ADD COLUMN backfill_uid INTEGER NOT NULL DEFAULT 0"
            )

    def _migrate_v3(self, connection: sqlite3.Connection) -> None:
        """hidden_by_tag, thread columns, FTS recipient/category alignment."""
        email_cols = self._table_columns(connection, "emails")
        for col, ddl in (
            ("hidden_by_tag", "ALTER TABLE emails ADD COLUMN hidden_by_tag INTEGER NOT NULL DEFAULT 0"),
            ("thread_id", "ALTER TABLE emails ADD COLUMN thread_id TEXT NOT NULL DEFAULT ''"),
            ("in_reply_to", "ALTER TABLE emails ADD COLUMN in_reply_to TEXT NOT NULL DEFAULT ''"),
        ):
            if email_cols and col not in email_cols:
                connection.execute(ddl)

        fts_cols = self._table_columns(connection, "email_search")
        if fts_cols and "recipient" not in fts_cols:
            connection.execute("DROP TABLE IF EXISTS email_search")
            connection.execute(
                """
                CREATE VIRTUAL TABLE email_search USING fts5(
                    email_id UNINDEXED,
                    subject,
                    sender,
                    recipient,
                    body,
                    bullet_summary,
                    keywords,
                    category
                )
                """
            )
            rows = connection.execute(
                "SELECT email_id, subject, sender, recipient, body, bullet_summary, keywords, category FROM emails"
            ).fetchall()
            for row in rows:
                connection.execute(
                    """
                    INSERT INTO email_search (
                        email_id, subject, sender, recipient, body, bullet_summary, keywords, category
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row[0],
                        row[1],
                        row[2] or "",
                        row[3] or "",
                        row[4],
                        row[5],
                        row[6],
                        row[7],
                    ),
                )
            self.fts_enabled = True

    def _migrate_v4(self, connection: sqlite3.Connection) -> None:
        """Pending signup verification codes (hashed, short-lived)."""
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS email_verifications (
                email TEXT PRIMARY KEY,
                code_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_sent_at TEXT NOT NULL
            )
            """
        )

    def _migrate_v5(self, connection: sqlite3.Connection) -> None:
        """IMAP sync prefs and per-folder UID checkpoints."""
        cols = self._table_columns(connection, "imap_accounts")
        if cols and "sync_since_date" not in cols:
            connection.execute("ALTER TABLE imap_accounts ADD COLUMN sync_since_date TEXT")
        if cols and "sync_max_count" not in cols:
            connection.execute(
                "ALTER TABLE imap_accounts ADD COLUMN sync_max_count INTEGER NOT NULL DEFAULT 200"
            )

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS imap_folder_sync (
                account_id INTEGER NOT NULL,
                folder TEXT NOT NULL,
                last_uid INTEGER NOT NULL DEFAULT 0,
                backfill_uid INTEGER NOT NULL DEFAULT 0,
                uidvalidity INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY (account_id, folder)
            )
            """
        )

        # ponytail: one-time copy INBOX state from legacy account columns.
        rows = connection.execute(
            "SELECT id, last_uid, backfill_uid, uidvalidity FROM imap_accounts"
        ).fetchall()
        for row in rows:
            connection.execute(
                """
                INSERT OR IGNORE INTO imap_folder_sync
                    (account_id, folder, last_uid, backfill_uid, uidvalidity, enabled)
                VALUES (?, 'INBOX', ?, ?, ?, 1)
                """,
                (row["id"], row["last_uid"], row["backfill_uid"], row["uidvalidity"]),
            )

    def _migrate_v6(self, connection: sqlite3.Connection) -> None:
        """Background job status/logs and generic per-user key-value cache."""
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_jobs (
                id TEXT PRIMARY KEY,
                user_email TEXT NOT NULL,
                job_type TEXT NOT NULL,
                status TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                current_step INTEGER NOT NULL DEFAULT 0,
                total_steps INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                log_json TEXT NOT NULL DEFAULT '[]',
                error TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_jobs_user ON user_jobs(user_email, created_at DESC)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_kv (
                user_email TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL DEFAULT '',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_email, key)
            )
            """
        )

    def initialize(self) -> None:
        with self._connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version < 1:
                self._migrate_v1(connection)
                connection.execute("PRAGMA user_version = 1")
                version = 1
            if version < 2:
                self._migrate_v2(connection)
                connection.execute("PRAGMA user_version = 2")
                version = 2
            if version < 3:
                self._migrate_v3(connection)
                connection.execute("PRAGMA user_version = 3")
                version = 3
            if version < 4:
                self._migrate_v4(connection)
                connection.execute("PRAGMA user_version = 4")
                version = 4
            if version < 5:
                self._migrate_v5(connection)
                connection.execute("PRAGMA user_version = 5")
                version = 5
            if version < 6:
                self._migrate_v6(connection)
                connection.execute("PRAGMA user_version = 6")
            try:
                connection.execute("SELECT email_id FROM email_search LIMIT 0")
                self.fts_enabled = True
            except sqlite3.OperationalError:
                self.fts_enabled = False

    def _write_search_index(
        self,
        connection: sqlite3.Connection,
        email_id: str,
        subject: str,
        sender: str,
        recipient: str,
        body: str,
        bullet_summary: list[str],
        keywords: list[str],
        category: str,
        search_blob: str,
    ) -> None:
        connection.execute(
            "UPDATE emails SET search_blob = ? WHERE email_id = ?",
            (search_blob, email_id),
        )
        if self.fts_enabled:
            connection.execute("DELETE FROM email_search WHERE email_id = ?", (email_id,))
            connection.execute(
                """
                INSERT INTO email_search (
                    email_id, subject, sender, recipient, body, bullet_summary, keywords, category
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email_id,
                    subject,
                    sender,
                    recipient,
                    body,
                    " ".join(bullet_summary),
                    " ".join(keywords),
                    category,
                ),
            )

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
                        in_reply_to,
                        thread_id,
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
                        search_blob,
                        is_mailing_list,
                        ai_analyzed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(email_id) DO UPDATE SET
                        user_email=excluded.user_email,
                        message_id=excluded.message_id,
                        in_reply_to=excluded.in_reply_to,
                        thread_id=excluded.thread_id,
                        source_name=excluded.source_name,
                        source_account=excluded.source_account,
                        subject=excluded.subject,
                        sender=excluded.sender,
                        recipient=excluded.recipient,
                        cc=excluded.cc,
                        received_at=excluded.received_at,
                        body=excluded.body,
                        preview=excluded.preview,
                        bullet_summary=CASE WHEN excluded.ai_analyzed=1 THEN excluded.bullet_summary ELSE emails.bullet_summary END,
                        ai_analyzed=MAX(emails.ai_analyzed, excluded.ai_analyzed),
                        category=excluded.category,
                        priority_score=excluded.priority_score,
                        keywords=excluded.keywords,
                        search_blob=excluded.search_blob,
                        is_mailing_list=excluded.is_mailing_list
                    """,
                    (
                        record["email_id"],
                        record["user_email"],
                        record["message_id"],
                        record.get("in_reply_to", ""),
                        record.get("thread_id", ""),
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
                        record.get("is_mailing_list", 0),
                        record.get("ai_analyzed", 0),
                    ),
                )
                keywords_list = record["keywords"]
                self._write_search_index(
                    connection,
                    record["email_id"],
                    record["subject"],
                    record["sender"],
                    record.get("recipient", ""),
                    record["body"],
                    record["bullet_summary"],
                    keywords_list,
                    record["category"],
                    record["search_blob"],
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
        offset: int = 0,
        category: str | None = None,
        user_email: str | None = None,
        source_account: str | None = None,
        sender_filter: str | None = None,
        recipient_filter: str | None = None,
        subject_filter: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        exclude_hidden: bool = True,
        only_hidden: bool = False,
        tag_filter: int | None = None,
        sort: str = "date_desc",
        only_unread: bool = False,
        exclude_mailing_list: bool = False,
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
        if sender_filter:
            conditions.append("sender LIKE ?")
            params.append(f"%{sender_filter}%")
        if recipient_filter:
            conditions.append("recipient LIKE ?")
            params.append(f"%{recipient_filter}%")
        if subject_filter:
            conditions.append("subject LIKE ?")
            params.append(f"%{subject_filter}%")
        if date_from:
            conditions.append("COALESCE(received_at, created_at) >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("COALESCE(received_at, created_at) <= ?")
            params.append(date_to + "T23:59:59" if "T" not in date_to else date_to)
        if only_hidden:
            conditions.append("is_hidden = 1")
        elif exclude_hidden:
            conditions.append("is_hidden = 0")
        if only_unread:
            conditions.append("is_read = 0")
        if exclude_mailing_list:
            conditions.append("is_mailing_list = 0")

        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        if tag_filter is not None:
            query = (
                f"SELECT emails.* FROM emails "
                f"JOIN email_tags ON email_tags.email_id = emails.email_id "
                f"AND email_tags.tag_id = ?"
            )
            params = [tag_filter] + params
            query += where_clause
        else:
            query += where_clause

        _order = {
            "date_asc":  "COALESCE(received_at, created_at) ASC",
            "priority":  "priority_score DESC, COALESCE(received_at, created_at) DESC",
        }.get(sort, "COALESCE(received_at, created_at) DESC")
        query += f" ORDER BY {_order} LIMIT ? OFFSET ?"
        params.append(limit)
        params.append(max(0, offset))

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()

        return [self._deserialize_row(row) for row in rows]

    def count_emails(
        self,
        category: str | None = None,
        user_email: str | None = None,
        source_account: str | None = None,
        sender_filter: str | None = None,
        recipient_filter: str | None = None,
        subject_filter: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        exclude_hidden: bool = True,
        only_hidden: bool = False,
        tag_filter: int | None = None,
        only_unread: bool = False,
        exclude_mailing_list: bool = False,
        search_term: str | None = None,
    ) -> int:
        """Count emails matching the same filters as list_emails / search."""
        if search_term:
            return len(
                self.search(
                    search_term,
                    limit=10000,
                    user_email=user_email,
                    source_account=source_account,
                    sender_filter=sender_filter,
                    recipient_filter=recipient_filter,
                    subject_filter=subject_filter,
                    category=category,
                    date_from=date_from,
                    date_to=date_to,
                    exclude_hidden=exclude_hidden,
                    only_hidden=only_hidden,
                    tag_filter=tag_filter,
                    only_unread=only_unread,
                    exclude_mailing_list=exclude_mailing_list,
                )
            )

        query = "SELECT COUNT(*) FROM emails"
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
        if sender_filter:
            conditions.append("sender LIKE ?")
            params.append(f"%{sender_filter}%")
        if recipient_filter:
            conditions.append("recipient LIKE ?")
            params.append(f"%{recipient_filter}%")
        if subject_filter:
            conditions.append("subject LIKE ?")
            params.append(f"%{subject_filter}%")
        if date_from:
            conditions.append("COALESCE(received_at, created_at) >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("COALESCE(received_at, created_at) <= ?")
            params.append(date_to + "T23:59:59" if "T" not in date_to else date_to)
        if only_hidden:
            conditions.append("is_hidden = 1")
        elif exclude_hidden:
            conditions.append("is_hidden = 0")
        if only_unread:
            conditions.append("is_read = 0")
        if exclude_mailing_list:
            conditions.append("is_mailing_list = 0")

        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        if tag_filter is not None:
            query = (
                "SELECT COUNT(*) FROM emails "
                "JOIN email_tags ON email_tags.email_id = emails.email_id "
                "AND email_tags.tag_id = ?"
            )
            params = [tag_filter] + params
            query += where_clause
        else:
            query += where_clause

        with self._connect() as connection:
            return int(connection.execute(query, params).fetchone()[0])

    def list_thread_emails(self, thread_id: str, user_email: str, limit: int = 20) -> list[dict]:
        if not thread_id:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM emails
                WHERE user_email = ? AND thread_id = ? AND is_hidden = 0
                ORDER BY COALESCE(received_at, created_at) ASC
                LIMIT ?
                """,
                (user_email, thread_id, limit),
            ).fetchall()
        return [self._deserialize_row(row) for row in rows]

    def search(
        self,
        search_term: str,
        limit: int = 100,
        offset: int = 0,
        user_email: str | None = None,
        source_account: str | None = None,
        sender_filter: str | None = None,
        recipient_filter: str | None = None,
        subject_filter: str | None = None,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        exclude_hidden: bool = True,
        only_hidden: bool = False,
        tag_filter: int | None = None,
        sort: str = "date_desc",
        only_unread: bool = False,
        exclude_mailing_list: bool = False,
    ) -> list[dict]:
        # Build additional filter clauses for both FTS (JOIN) and LIKE paths.
        fts_extra: list[str] = []
        fts_params: list[object] = []
        like_extra: list[str] = []
        like_params: list[object] = []

        def _add(fts_col: str, like_col: str, op: str, value: object) -> None:
            fts_extra.append(f"emails.{fts_col} {op} ?")
            fts_params.append(value)
            like_extra.append(f"{like_col} {op} ?")
            like_params.append(value)

        if source_account:
            _add("source_account", "source_account", "=", source_account)
        if sender_filter:
            _add("sender", "sender", "LIKE", f"%{sender_filter}%")
        if recipient_filter:
            _add("recipient", "recipient", "LIKE", f"%{recipient_filter}%")
        if subject_filter:
            _add("subject", "subject", "LIKE", f"%{subject_filter}%")
        if category:
            _add("category", "category", "=", category)
        if date_from:
            fts_extra.append("COALESCE(emails.received_at, emails.created_at) >= ?")
            fts_params.append(date_from)
            like_extra.append("COALESCE(received_at, created_at) >= ?")
            like_params.append(date_from)
        if date_to:
            _date_to_val = date_to + "T23:59:59" if "T" not in date_to else date_to
            fts_extra.append("COALESCE(emails.received_at, emails.created_at) <= ?")
            fts_params.append(_date_to_val)
            like_extra.append("COALESCE(received_at, created_at) <= ?")
            like_params.append(_date_to_val)
        if only_hidden:
            _add("is_hidden", "is_hidden", "=", 1)
        elif exclude_hidden:
            _add("is_hidden", "is_hidden", "=", 0)
        if tag_filter is not None:
            fts_extra.append("emails.email_id IN (SELECT email_id FROM email_tags WHERE tag_id = ?)")
            fts_params.append(tag_filter)
            like_extra.append("email_id IN (SELECT email_id FROM email_tags WHERE tag_id = ?)")
            like_params.append(tag_filter)
        if only_unread:
            _add("is_read", "is_read", "=", 0)
        if exclude_mailing_list:
            _add("is_mailing_list", "is_mailing_list", "=", 0)

        fts_clause = (" AND " + " AND ".join(fts_extra)) if fts_extra else ""
        like_clause = (" AND " + " AND ".join(like_extra)) if like_extra else ""
        filter_params = list(like_params)

        _order = {
            "date_asc":  "COALESCE(received_at, created_at) ASC",
            "priority":  "priority_score DESC, COALESCE(received_at, created_at) DESC",
        }.get(sort, "COALESCE(received_at, created_at) DESC")
        _fts_order = _order.replace("received_at", "emails.received_at").replace("created_at", "emails.created_at")

        with self._connect() as connection:
            wildcard = f"%{search_term}%"
            text_match = (
                "(subject LIKE ? OR sender LIKE ? OR recipient LIKE ? OR body LIKE ? "
                "OR bullet_summary LIKE ? OR keywords LIKE ? OR category LIKE ?)"
            )
            text_wildcards = [wildcard] * 7

            if self.fts_enabled:
                try:
                    if user_email:
                        rows = connection.execute(
                            f"""
                            SELECT emails.*
                            FROM email_search
                            JOIN emails ON emails.email_id = email_search.email_id
                            WHERE email_search MATCH ? AND emails.user_email = ?{fts_clause}
                            ORDER BY {_fts_order}
                            LIMIT ? OFFSET ?
                            """,
                            (search_term, user_email, *fts_params, limit, max(0, offset)),
                        ).fetchall()
                    else:
                        rows = connection.execute(
                            f"""
                            SELECT emails.*
                            FROM email_search
                            JOIN emails ON emails.email_id = email_search.email_id
                            WHERE email_search MATCH ?{fts_clause}
                            ORDER BY {_fts_order}
                            LIMIT ? OFFSET ?
                            """,
                            (search_term, *fts_params, limit, max(0, offset)),
                        ).fetchall()
                except sqlite3.OperationalError:
                    if user_email:
                        rows = connection.execute(
                            f"""
                            SELECT * FROM emails
                            WHERE {text_match} AND user_email = ?{like_clause}
                            ORDER BY {_order}
                            LIMIT ? OFFSET ?
                            """,
                            (*text_wildcards, user_email, *filter_params, limit, max(0, offset)),
                        ).fetchall()
                    else:
                        rows = connection.execute(
                            f"""
                            SELECT * FROM emails
                            WHERE {text_match}{like_clause}
                            ORDER BY {_order}
                            LIMIT ? OFFSET ?
                            """,
                            (*text_wildcards, *filter_params, limit, max(0, offset)),
                        ).fetchall()
            else:
                if user_email:
                    rows = connection.execute(
                        f"""
                        SELECT * FROM emails
                        WHERE {text_match} AND user_email = ?{like_clause}
                        ORDER BY {_order}
                        LIMIT ? OFFSET ?
                        """,
                        (*text_wildcards, user_email, *filter_params, limit, max(0, offset)),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        f"""
                        SELECT * FROM emails
                        WHERE {text_match}{like_clause}
                        ORDER BY {_order}
                        LIMIT ? OFFSET ?
                        """,
                        (*text_wildcards, *filter_params, limit, max(0, offset)),
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

    def update_imap_password(self, account_id: int, user_email: str, encrypted_password: str) -> bool:
        """Replace stored IMAP ciphertext. Return True if a row was updated."""
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE imap_accounts SET encrypted_password = ?
                WHERE id = ? AND user_email = ?
                """,
                (encrypted_password, account_id, user_email),
            )
            return cursor.rowcount > 0

    def update_imap_sync_prefs(
        self,
        account_id: int,
        sync_since_date: str | None,
        sync_max_count: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE imap_accounts
                SET sync_since_date = ?, sync_max_count = ?
                WHERE id = ?
                """,
                (sync_since_date, sync_max_count, account_id),
            )

    def get_folder_sync(self, account_id: int, folder: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM imap_folder_sync WHERE account_id = ? AND folder = ?",
                (account_id, folder),
            ).fetchone()
        return dict(row) if row else None

    def list_folder_sync(self, account_id: int) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM imap_folder_sync WHERE account_id = ? ORDER BY folder",
                (account_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_enabled_folders(self, account_id: int) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT folder FROM imap_folder_sync WHERE account_id = ? AND enabled = 1 ORDER BY folder",
                (account_id,),
            ).fetchall()
        folders = [row["folder"] for row in rows]
        return folders if folders else ["INBOX"]

    def set_folder_enabled(self, account_id: int, folder: str, enabled: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO imap_folder_sync (account_id, folder, enabled)
                VALUES (?, ?, ?)
                ON CONFLICT(account_id, folder) DO UPDATE SET enabled = excluded.enabled
                """,
                (account_id, folder, 1 if enabled else 0),
            )

    def ensure_folder_sync_rows(self, account_id: int, folders: list[str]) -> None:
        with self._connect() as connection:
            for folder in folders:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO imap_folder_sync (account_id, folder, enabled)
                    VALUES (?, ?, 1)
                    """,
                    (account_id, folder),
                )

    def update_folder_sync(
        self,
        account_id: int,
        folder: str,
        last_uid: int,
        backfill_uid: int,
        uidvalidity: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO imap_folder_sync (account_id, folder, last_uid, backfill_uid, uidvalidity, enabled)
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(account_id, folder) DO UPDATE SET
                    last_uid = excluded.last_uid,
                    backfill_uid = excluded.backfill_uid,
                    uidvalidity = excluded.uidvalidity
                """,
                (account_id, folder, last_uid, backfill_uid, uidvalidity),
            )

    def account_has_older_mail(self, account_id: int) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM imap_folder_sync
                WHERE account_id = ? AND enabled = 1 AND backfill_uid > 0
                LIMIT 1
                """,
                (account_id,),
            ).fetchone()
        return row is not None

    def count_ai_stats(self, user_email: str) -> tuple[int, int]:
        with self._connect() as connection:
            analyzed = connection.execute(
                "SELECT COUNT(*) FROM emails WHERE user_email = ? AND ai_analyzed = 1",
                (user_email,),
            ).fetchone()[0]
            total = connection.execute(
                "SELECT COUNT(*) FROM emails WHERE user_email = ?",
                (user_email,),
            ).fetchone()[0]
        return int(analyzed), int(total) - int(analyzed)

    def list_unanalyzed_email_ids(self, user_email: str, limit: int = 100) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT email_id FROM emails
                WHERE user_email = ? AND ai_analyzed = 0
                ORDER BY received_at DESC
                LIMIT ?
                """,
                (user_email, limit),
            ).fetchall()
        return [row["email_id"] for row in rows]

    def list_unanalyzed_emails(self, user_email: str, limit: int = 40) -> list[dict]:
        """Recent emails that still need a Groq summary."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM emails
                WHERE user_email = ? AND ai_analyzed = 0
                ORDER BY received_at DESC
                LIMIT ?
                """,
                (user_email, limit),
            ).fetchall()
        return [self._deserialize_row(row) for row in rows if row]

    def get_email_tags_batch(self, email_ids: list[str]) -> dict[str, list[dict]]:
        if not email_ids:
            return {}
        placeholders = ",".join("?" * len(email_ids))
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT email_tags.email_id, user_tags.id, user_tags.name, user_tags.color
                FROM email_tags
                JOIN user_tags ON user_tags.id = email_tags.tag_id
                WHERE email_tags.email_id IN ({placeholders})
                """,
                email_ids,
            ).fetchall()
        result: dict[str, list[dict]] = {eid: [] for eid in email_ids}
        for row in rows:
            result[row["email_id"]].append(
                {"id": row["id"], "name": row["name"], "color": row["color"]}
            )
        return result

    def update_imap_last_sync(
        self,
        account_id: int,
        last_uid: int,
        backfill_uid: int | None = None,
        uidvalidity: int | None = None,
    ) -> None:
        with self._connect() as connection:
            if backfill_uid is not None and uidvalidity is not None:
                connection.execute(
                    """
                    UPDATE imap_accounts
                    SET last_uid = ?, backfill_uid = ?, uidvalidity = ?, last_synced = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (last_uid, backfill_uid, uidvalidity, account_id),
                )
            else:
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

    def set_kv(self, user_email: str, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_kv (user_email, key, value, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_email, key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=excluded.updated_at
                """,
                (user_email, key, value),
            )

    def get_kv(self, user_email: str, key: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM user_kv WHERE user_email = ? AND key = ?",
                (user_email, key),
            ).fetchone()
        return row["value"] if row else ""

    def _job_from_row(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        job = dict(row)
        try:
            job["log"] = json.loads(job.pop("log_json") or "[]")
        except (TypeError, ValueError):
            job["log"] = []
        total = int(job.get("total_steps") or 0)
        current = int(job.get("current_step") or 0)
        if total > 0:
            job["percent"] = min(100, int(current * 100 / total))
        elif job.get("status") == "done":
            job["percent"] = 100
        else:
            job["percent"] = 0
        return job

    def job_was_cancelled(self, job_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM user_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return bool(row) and row["status"] == "cancelled"

    def cancel_active_jobs(self, user_email: str) -> list[str]:
        """Mark queued/running jobs cancelled. Return cancelled job ids."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, log_json FROM user_jobs
                WHERE user_email = ? AND status IN ('queued', 'running')
                """,
                (user_email,),
            ).fetchall()
            ids: list[str] = []
            for row in rows:
                try:
                    log = json.loads(row["log_json"] or "[]")
                except (TypeError, ValueError):
                    log = []
                if not isinstance(log, list):
                    log = []
                log.append("Cancelled by user.")
                log = log[-40:]
                connection.execute(
                    """
                    UPDATE user_jobs
                    SET status = 'cancelled', message = ?, error = '', log_json = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ? AND status IN ('queued', 'running')
                    """,
                    ("Cancelled.", json.dumps(log), row["id"]),
                )
                ids.append(row["id"])
        return ids

    def create_job(self, user_email: str, job_type: str, label: str) -> str:
        """Insert a queued job and return its id."""
        job_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_jobs (id, user_email, job_type, status, label, log_json)
                VALUES (?, ?, ?, 'queued', ?, '[]')
                """,
                (job_id, user_email, job_type, label),
            )
        return job_id

    def update_job(self, job_id: str, **fields: object) -> None:
        allowed = {"status", "label", "current_step", "total_steps", "message", "error"}
        assignments: list[str] = []
        values: list[object] = []
        for key, value in fields.items():
            if key not in allowed or value is None:
                continue
            assignments.append(f"{key} = ?")
            values.append(value)
        if not assignments:
            return
        assignments.append("updated_at = CURRENT_TIMESTAMP")
        values.append(job_id)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM user_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None or row["status"] == "cancelled":
                return
            connection.execute(
                f"UPDATE user_jobs SET {', '.join(assignments)} WHERE id = ?",
                values,
            )

    def append_job_log(self, job_id: str, line: str, *, limit: int = 40) -> None:
        """Append a log line and set the job's current message to that line."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT log_json, status FROM user_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None or row["status"] == "cancelled":
                return
            try:
                log = json.loads(row["log_json"] or "[]")
            except (TypeError, ValueError):
                log = []
            if not isinstance(log, list):
                log = []
            log.append(line)
            log = log[-limit:]
            connection.execute(
                """
                UPDATE user_jobs
                SET log_json = ?, message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status != 'cancelled'
                """,
                (json.dumps(log), line, job_id),
            )

    def get_job(self, job_id: str, user_email: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM user_jobs WHERE id = ? AND user_email = ?",
                (job_id, user_email),
            ).fetchone()
        return self._job_from_row(row)

    def get_active_job(self, user_email: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM user_jobs
                WHERE user_email = ? AND status IN ('queued', 'running')
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_email,),
            ).fetchone()
        return self._job_from_row(row)

    def get_latest_job(self, user_email: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM user_jobs
                WHERE user_email = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_email,),
            ).fetchone()
        return self._job_from_row(row)

    def list_jobs(self, user_email: str, limit: int = 5) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM user_jobs
                WHERE user_email = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_email, limit),
            ).fetchall()
        return [job for row in rows if (job := self._job_from_row(row))]

    # ------------------------------------------------------------------
    # App-level account password (separate from Gmail/IMAP credentials)
    # ------------------------------------------------------------------

    def set_app_password(self, user_email: str, password_hash: str) -> None:
        """Store a hashed account password for this email-tools user."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_settings (user_email, app_password_hash, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_email) DO UPDATE SET
                    app_password_hash=excluded.app_password_hash,
                    updated_at=excluded.updated_at
                """,
                (user_email, password_hash),
            )

    def get_app_password_hash(self, user_email: str) -> str:
        """Return the stored app-password hash, or '' if none set."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT app_password_hash FROM user_settings WHERE user_email = ?",
                (user_email,),
            ).fetchone()
        if row and row["app_password_hash"]:
            return row["app_password_hash"]
        return ""

    def create_verification(
        self,
        email: str,
        code_hash: str,
        expires_at: str,
        last_sent_at: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO email_verifications (email, code_hash, expires_at, attempt_count, last_sent_at)
                VALUES (?, ?, ?, 0, ?)
                ON CONFLICT(email) DO UPDATE SET
                    code_hash=excluded.code_hash,
                    expires_at=excluded.expires_at,
                    attempt_count=0,
                    last_sent_at=excluded.last_sent_at
                """,
                (email, code_hash, expires_at, last_sent_at),
            )

    def get_verification(self, email: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT email, code_hash, expires_at, attempt_count, last_sent_at FROM email_verifications WHERE email = ?",
                (email,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def bump_verification_attempts(self, email: str) -> int:
        """Increment attempt_count and return the new value."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE email_verifications SET attempt_count = attempt_count + 1 WHERE email = ?",
                (email,),
            )
            row = connection.execute(
                "SELECT attempt_count FROM email_verifications WHERE email = ?",
                (email,),
            ).fetchone()
        return int(row["attempt_count"]) if row else 0

    def delete_verification(self, email: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM email_verifications WHERE email = ?", (email,))

    def update_email_summary(
        self,
        email_id: str,
        user_email: str,
        bullet_summary: list[str],
        keywords: list[str] | None = None,
        category: str | None = None,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT subject, sender, recipient, body, keywords, category FROM emails WHERE email_id = ? AND user_email = ?",
                (email_id, user_email),
            ).fetchone()
            if row is None:
                return

            kw = keywords if keywords is not None else json.loads(row["keywords"])
            cat = category if category is not None else row["category"]
            search_blob = " ".join(
                [
                    row["subject"],
                    row["sender"] or "",
                    row["recipient"] or "",
                    row["body"],
                    " ".join(bullet_summary),
                    " ".join(kw),
                    cat,
                ]
            )
            connection.execute(
                "UPDATE emails SET bullet_summary = ?, ai_analyzed = 1, search_blob = ? WHERE email_id = ? AND user_email = ?",
                (json.dumps(bullet_summary), search_blob, email_id, user_email),
            )
            self._write_search_index(
                connection,
                email_id,
                row["subject"],
                row["sender"] or "",
                row["recipient"] or "",
                row["body"],
                bullet_summary,
                kw,
                cat,
                search_blob,
            )

    def set_email_hidden(self, email_id: str, user_email: str, hidden: bool, *, by_tag: bool = False) -> None:
        with self._connect() as connection:
            if hidden:
                connection.execute(
                    "UPDATE emails SET is_hidden = 1, hidden_by_tag = ? WHERE email_id = ? AND user_email = ?",
                    (1 if by_tag else 0, email_id, user_email),
                )
            else:
                connection.execute(
                    "UPDATE emails SET is_hidden = 0, hidden_by_tag = 0 WHERE email_id = ? AND user_email = ?",
                    (email_id, user_email),
                )

    def set_email_read(self, email_id: str, user_email: str, read: bool = True) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE emails SET is_read = ? WHERE email_id = ? AND user_email = ?",
                (1 if read else 0, email_id, user_email),
            )

    def get_senders(self, user_email: str, limit: int = 150) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT sender FROM emails
                WHERE user_email = ? AND sender IS NOT NULL AND sender != ''
                ORDER BY sender
                LIMIT ?
                """,
                (user_email, limit),
            ).fetchall()
        return [row[0] for row in rows]

    def get_recipients(self, user_email: str, limit: int = 150) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT recipient FROM emails
                WHERE user_email = ? AND recipient IS NOT NULL AND recipient != ''
                ORDER BY recipient
                LIMIT ?
                """,
                (user_email, limit),
            ).fetchall()
        return [row[0] for row in rows]

    # ------------------------------------------------------------------
    # Custom tag management
    # ------------------------------------------------------------------

    def save_tag(self, user_email: str, name: str, color: str, use_ai: bool,
                 ai_instruction: str, hide_matching: bool) -> int:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_tags (user_email, name, color, use_ai, ai_instruction, hide_matching)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_email, name) DO UPDATE SET
                    color=excluded.color,
                    use_ai=excluded.use_ai,
                    ai_instruction=excluded.ai_instruction,
                    hide_matching=excluded.hide_matching
                """,
                (user_email, name, color, int(use_ai), ai_instruction, int(hide_matching)),
            )
            row = connection.execute(
                "SELECT id FROM user_tags WHERE user_email = ? AND name = ?",
                (user_email, name),
            ).fetchone()
        return row["id"]

    def update_tag(self, tag_id: int, user_email: str, name: str, color: str,
                   use_ai: bool, ai_instruction: str, hide_matching: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE user_tags SET name=?, color=?, use_ai=?, ai_instruction=?, hide_matching=?
                WHERE id=? AND user_email=?
                """,
                (name, color, int(use_ai), ai_instruction, int(hide_matching), tag_id, user_email),
            )

    def delete_tag(self, tag_id: int, user_email: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM user_tags WHERE id = ? AND user_email = ?",
                (tag_id, user_email),
            )

    def list_tags(self, user_email: str) -> list[dict]:
        with self._connect() as connection:
            tags = connection.execute(
                "SELECT * FROM user_tags WHERE user_email = ? ORDER BY created_at",
                (user_email,),
            ).fetchall()
            if not tags:
                return []

            tag_ids = [tag["id"] for tag in tags]
            placeholders = ",".join("?" * len(tag_ids))
            rule_rows = connection.execute(
                f"SELECT * FROM tag_rules WHERE tag_id IN ({placeholders}) ORDER BY id",
                tag_ids,
            ).fetchall()
            count_rows = connection.execute(
                f"""
                SELECT tag_id, COUNT(*) AS cnt FROM email_tags
                WHERE tag_id IN ({placeholders})
                GROUP BY tag_id
                """,
                tag_ids,
            ).fetchall()

        rules_by_tag: dict[int, list[dict]] = {tid: [] for tid in tag_ids}
        for rule in rule_rows:
            rules_by_tag[rule["tag_id"]].append(dict(rule))
        counts_by_tag = {row["tag_id"]: row["cnt"] for row in count_rows}

        result: list[dict] = []
        for tag in tags:
            tag_dict = dict(tag)
            tag_dict["rules"] = rules_by_tag.get(tag_dict["id"], [])
            tag_dict["email_count"] = counts_by_tag.get(tag_dict["id"], 0)
            result.append(tag_dict)
        return result

    def get_tag(self, tag_id: int, user_email: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM user_tags WHERE id = ? AND user_email = ?",
                (tag_id, user_email),
            ).fetchone()
            if row is None:
                return None
            tag = dict(row)
            rules = connection.execute(
                "SELECT * FROM tag_rules WHERE tag_id = ?",
                (tag_id,),
            ).fetchall()
            tag["rules"] = [dict(r) for r in rules]
        return tag

    def seed_tag_name_rules(self, tag_id: int, name: str) -> None:
        """Subject/body contains rules so Hide matching works without a custom filter."""
        phrase = name.strip()
        if not phrase:
            return
        self.save_tag_rule(tag_id, "subject", "contains", phrase)
        self.save_tag_rule(tag_id, "body", "contains", phrase)

    def save_tag_rule(self, tag_id: int, field: str, operator: str, value: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO tag_rules (tag_id, field, operator, value) VALUES (?, ?, ?, ?)",
                (tag_id, field, operator, value),
            )
        return cursor.lastrowid

    def delete_tag_rule(self, rule_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM tag_rules WHERE id = ?", (rule_id,))

    def clear_tag_rules(self, tag_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM tag_rules WHERE tag_id = ?", (tag_id,))

    def get_email_tags(self, email_id: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT user_tags.* FROM user_tags
                   JOIN email_tags ON email_tags.tag_id = user_tags.id
                   WHERE email_tags.email_id = ?""",
                (email_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def set_email_tags(self, email_id: str, tag_ids: list[int]) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM email_tags WHERE email_id = ?", (email_id,))
            for tag_id in tag_ids:
                connection.execute(
                    "INSERT OR IGNORE INTO email_tags (email_id, tag_id) VALUES (?, ?)",
                    (email_id, tag_id),
                )

    def _email_matches_rule(self, email: dict, rule: dict) -> bool:
        field = rule["field"]
        operator = rule["operator"]
        value = rule["value"].lower()
        haystack = (email.get(field) or "").lower()
        if operator == "contains":
            return value in haystack
        if operator == "equals":
            return haystack == value
        if operator == "starts_with":
            return haystack.startswith(value)
        if operator == "ends_with":
            return haystack.endswith(value)
        if operator == "not_contains":
            return value not in haystack
        return False

    def apply_manual_tags_to_email(self, email: dict, tags: list[dict]) -> list[int]:
        matched: list[int] = []
        for tag in tags:
            for rule in tag.get("rules", []):
                if self._email_matches_rule(email, rule):
                    matched.append(tag["id"])
                    break
        return matched

    def apply_all_manual_tags(self, user_email: str) -> int:
        tags = self.list_tags(user_email)
        for tag in tags:
            if tag["hide_matching"] and not tag["use_ai"] and not tag["rules"]:
                phrase = str(tag.get("name") or "").strip()
                if phrase:
                    self.seed_tag_name_rules(tag["id"], phrase)
                    tag["rules"] = [
                        {"field": "subject", "operator": "contains", "value": phrase},
                        {"field": "body", "operator": "contains", "value": phrase},
                    ]
        manual_tags = [t for t in tags if not t["use_ai"] or t["rules"]]
        if not manual_tags:
            return 0

        emails = self.list_emails(user_email=user_email, limit=10000, exclude_hidden=False)
        updated = 0
        hide_tag_ids = {t["id"] for t in manual_tags if t["hide_matching"]}

        with self._connect() as connection:
            for email in emails:
                matched_ids = set(self.apply_manual_tags_to_email(email, manual_tags))
                manual_tag_ids = {t["id"] for t in manual_tags}
                existing = {
                    row[0]
                    for row in connection.execute(
                        "SELECT tag_id FROM email_tags WHERE email_id = ?",
                        (email["email_id"],),
                    ).fetchall()
                }
                stale_manual = (existing & manual_tag_ids) - matched_ids
                for tag_id in stale_manual:
                    connection.execute(
                        "DELETE FROM email_tags WHERE email_id = ? AND tag_id = ?",
                        (email["email_id"], tag_id),
                    )
                    updated += 1
                for tag_id in matched_ids:
                    if tag_id not in existing:
                        connection.execute(
                            "INSERT OR IGNORE INTO email_tags (email_id, tag_id) VALUES (?, ?)",
                            (email["email_id"], tag_id),
                        )
                        updated += 1

                should_hide = bool(matched_ids & hide_tag_ids)
                if should_hide:
                    connection.execute(
                        "UPDATE emails SET is_hidden = 1, hidden_by_tag = 1 WHERE email_id = ? AND user_email = ?",
                        (email["email_id"], user_email),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE emails SET is_hidden = 0, hidden_by_tag = 0
                        WHERE email_id = ? AND user_email = ? AND hidden_by_tag = 1
                        """,
                        (email["email_id"], user_email),
                    )
        return updated