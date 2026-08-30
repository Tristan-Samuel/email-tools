from __future__ import annotations

import datetime
import json
import sqlite3
import uuid
from pathlib import Path

from .llm_text import sanitize_action_title


JOB_PHASE_WEIGHTS: dict[str, int] = {
    "fetch": 50,
    "summarize": 35,
    "tag": 10,
    "brief": 5,
}


def job_percent_from_phases(phases: dict) -> int:
    """Weighted percent across fetch / summarize / tag / brief meters."""
    total = 0.0
    for phase, weight in JOB_PHASE_WEIGHTS.items():
        entry = phases.get(phase) or {}
        current = int(entry.get("current") or 0)
        phase_total = int(entry.get("total") or 0)
        if phase_total > 0:
            total += weight * min(current, phase_total) / phase_total
    return min(100, int(total))


class EmailStore:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.fts_enabled = False

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
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

    def _migrate_v7(self, connection: sqlite3.Connection) -> None:
        """Per-phase job progress for fetch / summarize / tag / brief meters."""
        if "progress_json" not in self._table_columns(connection, "user_jobs"):
            connection.execute(
                "ALTER TABLE user_jobs ADD COLUMN progress_json TEXT NOT NULL DEFAULT '{}'"
            )

    def _migrate_v8(self, connection: sqlite3.Connection) -> None:
        """AI tag verdict cache so Groq does not re-scan every sync."""
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS email_tag_scans (
                email_id TEXT NOT NULL,
                tag_id INTEGER NOT NULL,
                verdict TEXT NOT NULL,
                scanned_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (email_id, tag_id)
            )
            """
        )

    def _migrate_v9(self, connection: sqlite3.Connection) -> None:
        """Sanitized HTML bodies and AI confirm-before-hide on tags."""
        email_cols = self._table_columns(connection, "emails")
        if email_cols and "body_html" not in email_cols:
            connection.execute(
                "ALTER TABLE emails ADD COLUMN body_html TEXT NOT NULL DEFAULT ''"
            )
        tag_cols = self._table_columns(connection, "user_tags")
        if tag_cols and "ai_confirm" not in tag_cols:
            connection.execute(
                "ALTER TABLE user_tags ADD COLUMN ai_confirm INTEGER NOT NULL DEFAULT 0"
            )

    def _migrate_v10(self, connection: sqlite3.Connection) -> None:
        """Intent triage columns, thread rollup, and sender VIP/hide rules."""
        email_cols = self._table_columns(connection, "emails")
        for col, ddl in (
            ("intent", "ALTER TABLE emails ADD COLUMN intent TEXT NOT NULL DEFAULT 'fyi'"),
            ("intent_reason", "ALTER TABLE emails ADD COLUMN intent_reason TEXT NOT NULL DEFAULT ''"),
            ("due_at", "ALTER TABLE emails ADD COLUMN due_at TEXT"),
            ("triage_status", "ALTER TABLE emails ADD COLUMN triage_status TEXT NOT NULL DEFAULT 'open'"),
            ("snooze_until", "ALTER TABLE emails ADD COLUMN snooze_until TEXT"),
            ("from_me", "ALTER TABLE emails ADD COLUMN from_me INTEGER NOT NULL DEFAULT 0"),
            ("urgency", "ALTER TABLE emails ADD COLUMN urgency INTEGER NOT NULL DEFAULT 0"),
        ):
            if email_cols and col not in email_cols:
                connection.execute(ddl)

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS thread_state (
                user_email TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                intent TEXT NOT NULL DEFAULT 'fyi',
                intent_reason TEXT NOT NULL DEFAULT '',
                due_at TEXT,
                triage_status TEXT NOT NULL DEFAULT 'open',
                snooze_until TEXT,
                urgency INTEGER NOT NULL DEFAULT 0,
                latest_email_id TEXT NOT NULL DEFAULT '',
                last_inbound_at TEXT,
                last_from_me_at TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_email, thread_id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_thread_state_user ON thread_state(user_email, urgency DESC)"
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sender_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                pattern TEXT NOT NULL,
                rule_type TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_email, pattern, rule_type)
            )
            """
        )

    def _migrate_v11(self, connection: sqlite3.Connection) -> None:
        """User placement locks on thread_state so AI rebuild cannot undo triage actions."""
        thread_cols = self._table_columns(connection, "thread_state")
        if not thread_cols:
            return
        for col, ddl in (
            ("on_todo", "ALTER TABLE thread_state ADD COLUMN on_todo INTEGER NOT NULL DEFAULT 0"),
            ("user_moved", "ALTER TABLE thread_state ADD COLUMN user_moved INTEGER NOT NULL DEFAULT 0"),
            ("user_action", "ALTER TABLE thread_state ADD COLUMN user_action TEXT NOT NULL DEFAULT ''"),
            ("user_action_at", "ALTER TABLE thread_state ADD COLUMN user_action_at TEXT"),
        ):
            if col not in thread_cols:
                connection.execute(ddl)

    def _migrate_v12(self, connection: sqlite3.Connection) -> None:
        """Per-user encrypted Gemini API key."""
        settings_cols = self._table_columns(connection, "user_settings")
        if settings_cols and "gemini_api_key" not in settings_cols:
            connection.execute(
                "ALTER TABLE user_settings ADD COLUMN gemini_api_key TEXT NOT NULL DEFAULT ''"
            )

    def _migrate_v13(self, connection: sqlite3.Connection) -> None:
        """Dedicated one-line and compact list summaries, separate from key-point bullets."""
        email_cols = self._table_columns(connection, "emails")
        if not email_cols:
            return
        if "line_summary" not in email_cols:
            connection.execute(
                "ALTER TABLE emails ADD COLUMN line_summary TEXT NOT NULL DEFAULT ''"
            )
        if "compact_summary" not in email_cols:
            connection.execute(
                "ALTER TABLE emails ADD COLUMN compact_summary TEXT NOT NULL DEFAULT ''"
            )

    def _migrate_v14(self, connection: sqlite3.Connection) -> None:
        """AI-extracted assignment items for the assignments board."""
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS assignment_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email TEXT NOT NULL,
                email_id TEXT NOT NULL,
                title TEXT NOT NULL,
                due_at TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                source TEXT NOT NULL DEFAULT 'ai',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_email, email_id, title)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_assignment_user ON assignment_items(user_email, status)"
        )

    def _migrate_v15(self, connection: sqlite3.Connection) -> None:
        """Gmail X-GM-THRID hex so Open in Gmail can open the conversation."""
        email_cols = self._table_columns(connection, "emails")
        if email_cols and "gmail_thrid" not in email_cols:
            connection.execute(
                "ALTER TABLE emails ADD COLUMN gmail_thrid TEXT NOT NULL DEFAULT ''"
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
                version = 6
            if version < 7:
                self._migrate_v7(connection)
                connection.execute("PRAGMA user_version = 7")
                version = 7
            if version < 8:
                self._migrate_v8(connection)
                connection.execute("PRAGMA user_version = 8")
                version = 8
            if version < 9:
                self._migrate_v9(connection)
                connection.execute("PRAGMA user_version = 9")
                version = 9
            if version < 10:
                self._migrate_v10(connection)
                connection.execute("PRAGMA user_version = 10")
                version = 10
            if version < 11:
                self._migrate_v11(connection)
                connection.execute("PRAGMA user_version = 11")
                version = 11
            if version < 12:
                self._migrate_v12(connection)
                connection.execute("PRAGMA user_version = 12")
                version = 12
            if version < 13:
                self._migrate_v13(connection)
                connection.execute("PRAGMA user_version = 13")
                version = 13
            if version < 14:
                self._migrate_v14(connection)
                connection.execute("PRAGMA user_version = 14")
                version = 14
            if version < 15:
                self._migrate_v15(connection)
                connection.execute("PRAGMA user_version = 15")
                version = 15
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
                        body_html,
                        preview,
                        bullet_summary,
                        line_summary,
                        compact_summary,
                        category,
                        priority_score,
                        keywords,
                        search_blob,
                        is_mailing_list,
                        ai_analyzed,
                        intent,
                        intent_reason,
                        due_at,
                        triage_status,
                        snooze_until,
                        from_me,
                        urgency,
                        gmail_thrid
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        body_html=CASE
                            WHEN excluded.body_html != '' THEN excluded.body_html
                            ELSE emails.body_html
                        END,
                        preview=excluded.preview,
                        bullet_summary=CASE WHEN excluded.ai_analyzed=1 THEN excluded.bullet_summary ELSE emails.bullet_summary END,
                        line_summary=CASE
                            WHEN excluded.ai_analyzed=1 OR emails.line_summary = '' THEN excluded.line_summary
                            ELSE emails.line_summary
                        END,
                        compact_summary=CASE
                            WHEN excluded.ai_analyzed=1 OR emails.compact_summary = '' THEN excluded.compact_summary
                            ELSE emails.compact_summary
                        END,
                        ai_analyzed=MAX(emails.ai_analyzed, excluded.ai_analyzed),
                        category=excluded.category,
                        priority_score=excluded.priority_score,
                        keywords=excluded.keywords,
                        search_blob=excluded.search_blob,
                        is_mailing_list=excluded.is_mailing_list,
                        from_me=CASE WHEN excluded.from_me=1 THEN 1 ELSE emails.from_me END,
                        gmail_thrid=CASE
                            WHEN excluded.gmail_thrid != '' THEN excluded.gmail_thrid
                            ELSE emails.gmail_thrid
                        END,
                        intent=CASE WHEN excluded.ai_analyzed=1 THEN excluded.intent ELSE emails.intent END,
                        intent_reason=CASE WHEN excluded.ai_analyzed=1 THEN excluded.intent_reason ELSE emails.intent_reason END,
                        due_at=CASE WHEN excluded.ai_analyzed=1 THEN excluded.due_at ELSE emails.due_at END,
                        urgency=CASE WHEN excluded.urgency > emails.urgency THEN excluded.urgency ELSE emails.urgency END
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
                        record.get("body_html") or "",
                        record["preview"],
                        json.dumps(record["bullet_summary"]),
                        record.get("line_summary") or "",
                        record.get("compact_summary") or "",
                        record["category"],
                        record["priority_score"],
                        json.dumps(record["keywords"]),
                        record["search_blob"],
                        record.get("is_mailing_list", 0),
                        record.get("ai_analyzed", 0),
                        record.get("intent", "fyi"),
                        record.get("intent_reason", ""),
                        record.get("due_at"),
                        record.get("triage_status", "open"),
                        record.get("snooze_until"),
                        1 if record.get("from_me") else 0,
                        record.get("urgency", 0),
                        record.get("gmail_thrid") or "",
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
        email["line_summary"] = email.get("line_summary") or ""
        email["compact_summary"] = email.get("compact_summary") or ""
        email["gmail_thrid"] = email.get("gmail_thrid") or ""
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
            "priority":  "urgency DESC, priority_score DESC, COALESCE(received_at, created_at) DESC",
            "urgency":   "urgency DESC, COALESCE(received_at, created_at) DESC",
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
            "urgency":   "urgency DESC, COALESCE(received_at, created_at) DESC",
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
                """
                SELECT COUNT(*) FROM emails
                WHERE user_email = ? AND ai_analyzed = 1 AND line_summary != ''
                """,
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
                WHERE user_email = ? AND (ai_analyzed = 0 OR line_summary = '')
                ORDER BY received_at DESC
                LIMIT ?
                """,
                (user_email, limit),
            ).fetchall()
        return [row["email_id"] for row in rows]

    def list_unanalyzed_emails(self, user_email: str, limit: int = 40) -> list[dict]:
        """Recent emails that still need an AI summary (or a dedicated list line)."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM emails
                WHERE user_email = ? AND (ai_analyzed = 0 OR line_summary = '')
                ORDER BY received_at DESC
                LIMIT ?
                """,
                (user_email, limit),
            ).fetchall()
        return [self._deserialize_row(row) for row in rows if row]

    def clear_ai_analyzed(self, user_email: str, source_account: str | None = None) -> int:
        """Mark mail as needing a fresh AI pass so list-line summaries can be regenerated."""
        query = "UPDATE emails SET ai_analyzed = 0 WHERE user_email = ?"
        params: list[object] = [user_email]
        if source_account:
            query += " AND source_account = ?"
            params.append(source_account)
        with self._connect() as connection:
            cursor = connection.execute(query, params)
            return int(cursor.rowcount)

    def reset_account_sync_cursors(self, account_id: int, user_email: str) -> bool:
        """Zero IMAP UID checkpoints so the next sync re-downloads the current window."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM imap_accounts WHERE id = ? AND user_email = ?",
                (account_id, user_email),
            ).fetchone()
            if row is None:
                return False
            connection.execute(
                """
                UPDATE imap_folder_sync
                SET last_uid = 0, backfill_uid = 0
                WHERE account_id = ?
                """,
                (account_id,),
            )
            connection.execute(
                """
                UPDATE imap_accounts
                SET last_uid = 0, backfill_uid = 0
                WHERE id = ?
                """,
                (account_id,),
            )
        return True

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
            return
        if key == "gemini_api_key":
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO user_settings (user_email, gemini_api_key, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_email) DO UPDATE SET
                        gemini_api_key=excluded.gemini_api_key,
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
        if key == "gemini_api_key":
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT gemini_api_key FROM user_settings WHERE user_email = ?",
                    (user_email,),
                ).fetchone()
            return row["gemini_api_key"] if row else ""
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
        try:
            phases = json.loads(job.pop("progress_json") or "{}")
        except (TypeError, ValueError):
            phases = {}
        if not isinstance(phases, dict):
            phases = {}
        job["phases"] = phases
        if phases:
            job["percent"] = job_percent_from_phases(phases)
        else:
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
        allowed = {"status", "label", "current_step", "total_steps", "message", "error", "progress_json"}
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

    def update_job_phase(
        self,
        job_id: str,
        phase: str,
        current: int,
        total: int,
        message: str | None = None,
    ) -> None:
        """Update one phase meter and recompute weighted job percent."""
        if phase not in JOB_PHASE_WEIGHTS:
            return
        with self._connect() as connection:
            row = connection.execute(
                "SELECT progress_json, status FROM user_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None or row["status"] == "cancelled":
                return
            try:
                phases = json.loads(row["progress_json"] or "{}")
            except (TypeError, ValueError):
                phases = {}
            if not isinstance(phases, dict):
                phases = {}
            phases[phase] = {"current": max(0, current), "total": max(0, total)}
            percent = job_percent_from_phases(phases)
            assignments = [
                "progress_json = ?",
                "current_step = ?",
                "total_steps = ?",
                "updated_at = CURRENT_TIMESTAMP",
            ]
            values: list[object] = [
                json.dumps(phases),
                percent,
                100,
            ]
            if message is not None:
                assignments.insert(0, "message = ?")
                values.insert(0, message)
            values.append(job_id)
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

    def set_gmail_thrid(self, email_id: str, user_email: str, thrid: str) -> None:
        hex_id = (thrid or "").strip().lower()
        if not hex_id:
            return
        with self._connect() as connection:
            connection.execute(
                "UPDATE emails SET gmail_thrid = ? WHERE email_id = ? AND user_email = ?",
                (hex_id, email_id, user_email),
            )

    def update_email_summary(
        self,
        email_id: str,
        user_email: str,
        bullet_summary: list[str],
        keywords: list[str] | None = None,
        category: str | None = None,
        line_summary: str = "",
        compact_summary: str = "",
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
                    line_summary,
                    compact_summary,
                    " ".join(bullet_summary),
                    " ".join(kw),
                    cat,
                ]
            )
            connection.execute(
                """
                UPDATE emails SET
                    bullet_summary = ?,
                    line_summary = ?,
                    compact_summary = ?,
                    ai_analyzed = 1,
                    search_blob = ?
                WHERE email_id = ? AND user_email = ?
                """,
                (
                    json.dumps(bullet_summary),
                    line_summary,
                    compact_summary,
                    search_blob,
                    email_id,
                    user_email,
                ),
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

    def save_tag(
        self,
        user_email: str,
        name: str,
        color: str,
        use_ai: bool,
        ai_instruction: str,
        hide_matching: bool,
        ai_confirm: bool = False,
    ) -> int:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_tags (user_email, name, color, use_ai, ai_instruction, hide_matching, ai_confirm)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_email, name) DO UPDATE SET
                    color=excluded.color,
                    use_ai=excluded.use_ai,
                    ai_instruction=excluded.ai_instruction,
                    hide_matching=excluded.hide_matching,
                    ai_confirm=excluded.ai_confirm
                """,
                (
                    user_email,
                    name,
                    color,
                    int(use_ai),
                    ai_instruction,
                    int(hide_matching),
                    int(ai_confirm),
                ),
            )
            row = connection.execute(
                "SELECT id FROM user_tags WHERE user_email = ? AND name = ?",
                (user_email, name),
            ).fetchone()
        return row["id"]

    def update_tag(
        self,
        tag_id: int,
        user_email: str,
        name: str,
        color: str,
        use_ai: bool,
        ai_instruction: str,
        hide_matching: bool,
        ai_confirm: bool = False,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE user_tags SET name=?, color=?, use_ai=?, ai_instruction=?, hide_matching=?, ai_confirm=?
                WHERE id=? AND user_email=?
                """,
                (
                    name,
                    color,
                    int(use_ai),
                    ai_instruction,
                    int(hide_matching),
                    int(ai_confirm),
                    tag_id,
                    user_email,
                ),
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

    DEFAULT_TAG_DEFS: list[dict] = [
        {
            "name": "School",
            "color": "#4a7c59",
            "hide_matching": False,
            "use_ai": False,
            "synonyms": [
                ("sender", "contains", "admissions"),
                ("sender", "contains", "university"),
                ("sender", "contains", "college"),
                ("sender", "contains", ".edu"),
                ("sender", "contains", "ghcds"),
                ("sender", "contains", "school"),
                ("sender", "contains", ".k12."),
                ("subject", "contains", "admissions"),
                ("body", "contains", "campus"),
                ("body", "contains", "enroll"),
                ("body", "contains", "university"),
                ("body", "contains", "college"),
            ],
        },
        {
            "name": "Marketing",
            "color": "#c66150",
            "hide_matching": True,
            "use_ai": False,
            "synonyms": [
                ("sender", "contains", "unsubscribe"),
                ("sender", "contains", "promo"),
                ("sender", "contains", "marketing"),
                ("subject", "contains", "unsubscribe"),
                ("subject", "contains", "promo"),
                ("subject", "contains", "discount"),
                ("subject", "contains", "sale"),
                ("body", "contains", "unsubscribe"),
                ("body", "contains", "campaign"),
            ],
        },
        {
            "name": "Newsletters",
            "color": "#6b7280",
            "hide_matching": True,
            "use_ai": False,
            "synonyms": [
                ("sender", "contains", "newsletter"),
                ("sender", "contains", "digest"),
                ("subject", "contains", "newsletter"),
                ("subject", "contains", "digest"),
                ("body", "contains", "newsletter"),
                ("body", "contains", "weekly digest"),
            ],
        },
    ]

    def seed_default_tag_rules(self, tag_id: int, synonyms: list[tuple[str, str, str]]) -> None:
        for field, operator, value in synonyms:
            self.save_tag_rule(tag_id, field, operator, value)

    def ensure_default_tags(self, user_email: str) -> None:
        """Create School / Marketing / Newsletters with synonym rules when missing."""
        self._prune_obsolete_marketing_rules(user_email)
        existing = {t["name"].lower(): t for t in self.list_tags(user_email)}
        needs_apply = False
        for spec in self.DEFAULT_TAG_DEFS:
            name = spec["name"]
            tag = existing.get(name.lower())
            if tag is None:
                tag_id = self.save_tag(
                    user_email,
                    name,
                    spec["color"],
                    spec["use_ai"],
                    "",
                    spec["hide_matching"],
                )
                self.seed_default_tag_rules(tag_id, spec["synonyms"])
                needs_apply = True
            else:
                rule_keys = {
                    f"{r['field']}:{r['value'].lower()}"
                    for r in tag.get("rules", [])
                }
                missing = [
                    syn
                    for syn in spec["synonyms"]
                    if f"{syn[0]}:{syn[2].lower()}" not in rule_keys
                ]
                if missing:
                    self.seed_default_tag_rules(tag["id"], missing)
                    needs_apply = True
        if needs_apply:
            self.apply_all_manual_tags(user_email)

    def _prune_obsolete_marketing_rules(self, user_email: str) -> None:
        """Remove Marketing body rule for 'offer' — too many school false positives."""
        tags = self.list_tags(user_email)
        marketing = next((t for t in tags if t["name"].lower() == "marketing"), None)
        if not marketing:
            return
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM tag_rules
                WHERE tag_id = ? AND field = 'body' AND LOWER(value) = 'offer'
                """,
                (marketing["id"],),
            )

    SCHOOL_PROTECT_TAG = "school"

    def _school_protected(self, matched_ids: set[int], manual_tags: list[dict]) -> bool:
        for tag in manual_tags:
            if tag["name"].lower() == self.SCHOOL_PROTECT_TAG and tag["id"] in matched_ids:
                return True
        return False

    def list_hidden_by_tag(self, user_email: str, limit: int = 500) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM emails
                WHERE user_email = ? AND is_hidden = 1 AND hidden_by_tag = 1
                ORDER BY received_at DESC
                LIMIT ?
                """,
                (user_email, limit),
            ).fetchall()
        return [row for row in (self._deserialize_row(r) for r in rows) if row]

    def save_tag_scan(self, email_id: str, tag_id: int, verdict: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO email_tag_scans (email_id, tag_id, verdict, scanned_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(email_id, tag_id) DO UPDATE SET
                    verdict=excluded.verdict,
                    scanned_at=excluded.scanned_at
                """,
                (email_id, tag_id, verdict),
            )

    def get_tag_scans_for_email(self, email_id: str) -> dict[int, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT tag_id, verdict FROM email_tag_scans WHERE email_id = ?",
                (email_id,),
            ).fetchall()
        return {int(row["tag_id"]): str(row["verdict"]) for row in rows}

    def clear_tag_scans_for_tag(self, tag_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM email_tag_scans WHERE tag_id = ?", (tag_id,))

    def clear_all_tag_scans(self, user_email: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM email_tag_scans
                WHERE email_id IN (SELECT email_id FROM emails WHERE user_email = ?)
                """,
                (user_email,),
            )

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
        confirm_hide_tag_ids = {
            t["id"] for t in manual_tags if t["hide_matching"] and t.get("ai_confirm")
        }
        immediate_hide_tag_ids = hide_tag_ids - confirm_hide_tag_ids

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

                school_protected = self._school_protected(matched_ids, manual_tags)
                should_hide = (
                    bool(matched_ids & immediate_hide_tag_ids) and not school_protected
                )
                if should_hide:
                    connection.execute(
                        "UPDATE emails SET is_hidden = 1, hidden_by_tag = 1 WHERE email_id = ? AND user_email = ?",
                        (email["email_id"], user_email),
                    )
                elif not (matched_ids & hide_tag_ids):
                    connection.execute(
                        """
                        UPDATE emails SET is_hidden = 0, hidden_by_tag = 0
                        WHERE email_id = ? AND user_email = ? AND hidden_by_tag = 1
                        """,
                        (email["email_id"], user_email),
                    )
        return updated

    def list_thread_groups(self, user_email: str, source_account: str | None = None) -> dict[str, list[dict]]:
        """Return {thread_id: [emails...]} for non-hidden mail."""
        emails = self.list_emails(
            user_email=user_email,
            source_account=source_account,
            limit=5000,
            exclude_hidden=True,
            sort="date_asc",
        )
        groups: dict[str, list[dict]] = {}
        for email in emails:
            tid = email.get("thread_id") or email["email_id"]
            groups.setdefault(tid, []).append(email)
        return groups

    def upsert_thread_state(
        self,
        user_email: str,
        thread_id: str,
        *,
        summary: str,
        intent: str,
        intent_reason: str,
        due_at: str | None,
        triage_status: str,
        snooze_until: str | None,
        urgency: int,
        latest_email_id: str,
        last_inbound_at: str | None,
        last_from_me_at: str | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO thread_state (
                    user_email, thread_id, summary, intent, intent_reason, due_at,
                    triage_status, snooze_until, urgency, latest_email_id,
                    last_inbound_at, last_from_me_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_email, thread_id) DO UPDATE SET
                    summary=excluded.summary,
                    intent=CASE WHEN thread_state.user_moved = 1 THEN thread_state.intent ELSE excluded.intent END,
                    intent_reason=CASE WHEN thread_state.user_moved = 1 THEN thread_state.intent_reason ELSE excluded.intent_reason END,
                    due_at=CASE WHEN thread_state.user_moved = 1 THEN thread_state.due_at ELSE excluded.due_at END,
                    triage_status=CASE WHEN thread_state.user_moved = 1 THEN thread_state.triage_status ELSE excluded.triage_status END,
                    snooze_until=CASE WHEN thread_state.user_moved = 1 THEN thread_state.snooze_until ELSE excluded.snooze_until END,
                    urgency=excluded.urgency,
                    latest_email_id=excluded.latest_email_id,
                    last_inbound_at=excluded.last_inbound_at,
                    last_from_me_at=excluded.last_from_me_at,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    user_email,
                    thread_id,
                    summary,
                    intent,
                    intent_reason,
                    due_at,
                    triage_status,
                    snooze_until,
                    urgency,
                    latest_email_id,
                    last_inbound_at,
                    last_from_me_at,
                ),
            )

    def list_thread_states(
        self,
        user_email: str,
        *,
        source_account: str | None = None,
    ) -> list[dict]:
        query = """
            SELECT thread_state.*, emails.subject, emails.sender, emails.received_at,
                   emails.is_hidden, emails.is_read, emails.source_account
            FROM thread_state
            JOIN emails ON emails.email_id = thread_state.latest_email_id
            WHERE thread_state.user_email = ?
        """
        params: list[object] = [user_email]
        if source_account:
            query += " AND emails.source_account = ?"
            params.append(source_account)
        query += " ORDER BY thread_state.urgency DESC, thread_state.last_inbound_at DESC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def get_thread_state(self, user_email: str, thread_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM thread_state WHERE user_email = ? AND thread_id = ?",
                (user_email, thread_id),
            ).fetchone()
        return dict(row) if row else None

    def set_thread_triage_status(
        self,
        user_email: str,
        thread_id: str,
        *,
        triage_status: str,
        snooze_until: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE thread_state
                SET triage_status = ?, snooze_until = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_email = ? AND thread_id = ?
                """,
                (triage_status, snooze_until, user_email, thread_id),
            )
            connection.execute(
                """
                UPDATE emails
                SET triage_status = ?, snooze_until = ?
                WHERE user_email = ? AND thread_id = ?
                """,
                (triage_status, snooze_until, user_email, thread_id),
            )

    VALID_USER_ACTIONS = frozenset({
        "add_todo",
        "remove_todo",
        "dismiss_fyi",
        "clear_fyi",
        "done",
        "snooze",
        "hide",
    })

    def record_thread_user_action(
        self,
        user_email: str,
        thread_id: str,
        action: str,
        *,
        on_todo: bool | None = None,
        triage_status: str | None = None,
        snooze_until: str | None = None,
        intent: str | None = None,
        intent_reason: str | None = None,
        due_at: str | None = None,
        clear_user_moved: bool = False,
    ) -> None:
        """Stamp a user triage action so rebuild/Groq cannot undo it."""
        if action not in self.VALID_USER_ACTIONS:
            return
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        existing = self.get_thread_state(user_email, thread_id) or {}

        new_on_todo = int(on_todo) if on_todo is not None else int(existing.get("on_todo") or 0)
        new_triage_status = triage_status or existing.get("triage_status") or "open"
        new_snooze = snooze_until if snooze_until is not None else existing.get("snooze_until")
        new_intent = intent or existing.get("intent") or "fyi"
        new_reason = intent_reason if intent_reason is not None else existing.get("intent_reason") or ""
        new_due_at = due_at if due_at is not None else existing.get("due_at")
        user_moved = 0 if clear_user_moved else 1

        if action == "add_todo":
            new_on_todo = 1
            new_triage_status = "open"
            new_snooze = None
            new_intent = "i_owe"
            new_reason = "You added this to Do now"
        elif action == "remove_todo":
            new_on_todo = 0
            new_triage_status = "open"
            new_snooze = None
            new_intent = "fyi"
            new_reason = "You removed this from Do now"
        elif action in ("dismiss_fyi", "clear_fyi", "done"):
            new_on_todo = 0
            new_triage_status = "done"
            new_snooze = None
        elif action == "snooze":
            new_on_todo = 0
            new_triage_status = "snoozed"
        elif action == "hide":
            new_on_todo = 0
            new_intent = "noise"
            new_reason = "You hid this thread"

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO thread_state (
                    user_email, thread_id, summary, intent, intent_reason, due_at,
                    triage_status, snooze_until, urgency, latest_email_id,
                    last_inbound_at, last_from_me_at, on_todo, user_moved,
                    user_action, user_action_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, '', NULL, NULL, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_email, thread_id) DO UPDATE SET
                    on_todo = excluded.on_todo,
                    user_moved = excluded.user_moved,
                    user_action = excluded.user_action,
                    user_action_at = excluded.user_action_at,
                    triage_status = excluded.triage_status,
                    snooze_until = excluded.snooze_until,
                    intent = excluded.intent,
                    intent_reason = excluded.intent_reason,
                    due_at = excluded.due_at,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user_email,
                    thread_id,
                    existing.get("summary") or "",
                    new_intent,
                    new_reason,
                    new_due_at,
                    new_triage_status,
                    new_snooze,
                    new_on_todo,
                    user_moved,
                    action,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE emails
                SET triage_status = ?, snooze_until = ?, intent = ?, intent_reason = ?, due_at = ?
                WHERE user_email = ? AND thread_id = ?
                """,
                (
                    new_triage_status,
                    new_snooze,
                    new_intent,
                    new_reason,
                    new_due_at,
                    user_email,
                    thread_id,
                ),
            )

    def thread_user_lock_active(
        self,
        existing: dict | None,
        *,
        last_inbound_at: str | None,
        last_from_me_at: str | None,
        today: datetime.date,
    ) -> bool:
        """Return True when user placement should block AI intent/status changes."""
        if not existing or not existing.get("user_moved"):
            return False
        user_action_at = existing.get("user_action_at") or ""
        if user_action_at and last_inbound_at and last_inbound_at > user_action_at:
            return False
        if (
            last_from_me_at
            and last_inbound_at
            and last_from_me_at >= last_inbound_at
        ):
            return False
        if existing.get("triage_status") == "snoozed" and existing.get("snooze_until"):
            try:
                if datetime.date.fromisoformat(str(existing["snooze_until"])[:10]) <= today:
                    return False
            except ValueError:
                pass
        return True

    def clear_thread_user_lock(
        self,
        user_email: str,
        thread_id: str,
        *,
        clear_on_todo: bool = False,
    ) -> None:
        """Release user_moved after lock exceptions (new inbound, sent reply, snooze expiry)."""
        with self._connect() as connection:
            if clear_on_todo:
                connection.execute(
                    """
                    UPDATE thread_state
                    SET user_moved = 0, user_action = '', user_action_at = NULL,
                        on_todo = 0, updated_at = CURRENT_TIMESTAMP
                    WHERE user_email = ? AND thread_id = ?
                    """,
                    (user_email, thread_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE thread_state
                    SET user_moved = 0, user_action = '', user_action_at = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE user_email = ? AND thread_id = ?
                    """,
                    (user_email, thread_id),
                )

    def mark_threads_read(self, user_email: str, thread_ids: list[str]) -> int:
        if not thread_ids:
            return 0
        placeholders = ",".join("?" * len(thread_ids))
        with self._connect() as connection:
            connection.execute(
                f"""
                UPDATE emails SET is_read = 1
                WHERE user_email = ? AND thread_id IN ({placeholders})
                """,
                [user_email, *thread_ids],
            )
        return len(thread_ids)

    def update_email_triage_fields(
        self,
        email_id: str,
        user_email: str,
        *,
        intent: str,
        intent_reason: str,
        due_at: str | None,
        urgency: int,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE emails
                SET intent = ?, intent_reason = ?, due_at = ?, urgency = ?
                WHERE email_id = ? AND user_email = ?
                """,
                (intent, intent_reason, due_at, urgency, email_id, user_email),
            )

    def update_email_analysis(
        self,
        email_id: str,
        user_email: str,
        *,
        bullet_summary: list[str],
        intent: str = "fyi",
        intent_reason: str = "",
        due_at: str | None = None,
        urgency: int = 0,
        ai_analyzed: bool = True,
        keywords: list[str] | None = None,
        category: str | None = None,
        line_summary: str = "",
        compact_summary: str = "",
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT subject, sender, recipient, body, keywords, category, thread_id,
                       triage_status, intent, intent_reason, due_at
                FROM emails WHERE email_id = ? AND user_email = ?
                """,
                (email_id, user_email),
            ).fetchone()
            if row is None:
                return

            thread_id = row["thread_id"] or email_id
            existing = self.get_thread_state(user_email, thread_id)
            today = datetime.date.today()
            lock_active = False
            if existing and existing.get("user_moved"):
                lock_active = self.thread_user_lock_active(
                    existing,
                    last_inbound_at=existing.get("last_inbound_at"),
                    last_from_me_at=existing.get("last_from_me_at"),
                    today=today,
                )
            if lock_active:
                intent = existing.get("intent") or row["intent"] or intent
                intent_reason = existing.get("intent_reason") or row["intent_reason"] or ""
                due_at = existing.get("due_at") or row["due_at"]

            kw = keywords if keywords is not None else json.loads(row["keywords"])
            cat = category if category is not None else row["category"]
            search_blob = " ".join(
                [
                    row["subject"],
                    row["sender"] or "",
                    row["recipient"] or "",
                    row["body"],
                    line_summary,
                    compact_summary,
                    " ".join(bullet_summary),
                    " ".join(kw),
                    cat,
                    intent,
                    intent_reason or "",
                ]
            )
            connection.execute(
                """
                UPDATE emails SET
                    bullet_summary = ?,
                    line_summary = ?,
                    compact_summary = ?,
                    ai_analyzed = ?,
                    search_blob = ?,
                    intent = ?,
                    intent_reason = ?,
                    due_at = ?,
                    urgency = ?
                WHERE email_id = ? AND user_email = ?
                """,
                (
                    json.dumps(bullet_summary),
                    line_summary,
                    compact_summary,
                    1 if ai_analyzed else 0,
                    search_blob,
                    intent,
                    intent_reason,
                    due_at,
                    urgency,
                    email_id,
                    user_email,
                ),
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

    def list_sender_rules(self, user_email: str, rule_type: str | None = None) -> list[str]:
        query = "SELECT pattern FROM sender_rules WHERE user_email = ?"
        params: list[object] = [user_email]
        if rule_type:
            query += " AND rule_type = ?"
            params.append(rule_type)
        query += " ORDER BY created_at"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [row["pattern"] for row in rows]

    def save_sender_rule(self, user_email: str, pattern: str, rule_type: str) -> None:
        pattern = (pattern or "").strip().lower()
        if not pattern or rule_type not in ("vip", "always_hide"):
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO sender_rules (user_email, pattern, rule_type)
                VALUES (?, ?, ?)
                """,
                (user_email, pattern, rule_type),
            )

    def delete_sender_rule(self, rule_id: int, user_email: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM sender_rules WHERE id = ? AND user_email = ?",
                (rule_id, user_email),
            )

    def list_sender_rule_rows(self, user_email: str) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sender_rules WHERE user_email = ? ORDER BY rule_type, pattern",
                (user_email,),
            ).fetchall()
        return [dict(row) for row in rows]

    def enable_default_folders(self, account_id: int, folders: list[str]) -> None:
        """Enable INBOX and Sent-like folders by default."""
        from . import imap_service

        defaults = imap_service.default_enabled_folders(folders)
        self.ensure_folder_sync_rows(account_id, folders)
        with self._connect() as connection:
            connection.execute(
                "UPDATE imap_folder_sync SET enabled = 0 WHERE account_id = ?",
                (account_id,),
            )
            for folder in defaults:
                connection.execute(
                    """
                    INSERT INTO imap_folder_sync (account_id, folder, enabled)
                    VALUES (?, ?, 1)
                    ON CONFLICT(account_id, folder) DO UPDATE SET enabled = 1
                    """,
                    (account_id, folder),
                )

    def list_inbox_thread_heads(
        self,
        user_email: str,
        *,
        limit: int = 100,
        offset: int = 0,
        source_account: str | None = None,
        tag_filter: int | None = None,
        sort: str = "date_desc",
        only_unread: bool = False,
        exclude_mailing_list: bool = False,
        category: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        query: str | None = None,
    ) -> tuple[list[dict], int]:
        """One row per thread — latest message metadata plus thread_state when present."""
        if query:
            emails = self.search(
                query,
                limit=5000,
                user_email=user_email,
                source_account=source_account,
                tag_filter=tag_filter,
                only_unread=only_unread,
                exclude_mailing_list=exclude_mailing_list,
                category=category,
                date_from=date_from,
                date_to=date_to,
            )
        else:
            emails = self.list_emails(
                limit=5000,
                user_email=user_email,
                source_account=source_account,
                tag_filter=tag_filter,
                only_unread=only_unread,
                exclude_mailing_list=exclude_mailing_list,
                category=category,
                date_from=date_from,
                date_to=date_to,
                sort="date_desc",
            )
        by_thread: dict[str, dict] = {}
        for email in emails:
            tid = email.get("thread_id") or email["email_id"]
            existing = by_thread.get(tid)
            if existing is None:
                by_thread[tid] = {**email, "thread_count": 1}
            else:
                existing["thread_count"] = int(existing.get("thread_count") or 1) + 1
                if (email.get("received_at") or "") > (existing.get("received_at") or ""):
                    by_thread[tid] = {**email, "thread_count": existing["thread_count"]}

        rows = list(by_thread.values())
        if sort == "urgency" or sort == "priority":
            rows.sort(key=lambda r: (-int(r.get("urgency") or r.get("priority_score") or 0), r.get("received_at") or ""), reverse=False)
        elif sort == "date_asc":
            rows.sort(key=lambda r: r.get("received_at") or "")
        else:
            rows.sort(key=lambda r: r.get("received_at") or "", reverse=True)

        total = len(rows)
        page = rows[offset : offset + limit]
        thread_ids = [r.get("thread_id") or r["email_id"] for r in page]
        states = {
            s["thread_id"]: s
            for s in self.list_thread_states(user_email, source_account=source_account)
            if s["thread_id"] in thread_ids
        }
        for row in page:
            tid = row.get("thread_id") or row["email_id"]
            state = states.get(tid)
            if state:
                row["thread_summary"] = state.get("summary") or ""
                row["intent"] = state.get("intent") or row.get("intent") or "fyi"
                row["urgency"] = state.get("urgency") or row.get("urgency") or 0
        return page, total

    def get_imap_account_by_email(self, user_email: str, account_email: str) -> dict | None:
        acct = (account_email or "").strip().lower()
        if not acct:
            return None
        for row in self.list_imap_accounts(user_email):
            if (row.get("account_email") or "").strip().lower() == acct:
                return row
        return None

    def list_ai_intent_candidates(
        self,
        user_email: str,
        *,
        action_type: str = "find_topic",
        source_account: str | None = None,
        limit: int = 80,
    ) -> list[dict]:
        """Heuristic candidate pool for AI search/actions."""
        rows: list[dict] = []
        school_tag = next(
            (t for t in self.list_tags(user_email) if (t.get("name") or "").lower() == "school"),
            None,
        )
        if school_tag:
            rows.extend(
                self.list_emails(
                    limit=limit,
                    user_email=user_email,
                    source_account=source_account,
                    tag_filter=school_tag["id"],
                    sort="urgency",
                )
            )
        if action_type in ("list_assignments", "this_week", "find_topic"):
            with self._connect() as connection:
                q = """
                    SELECT * FROM emails
                    WHERE user_email = ? AND is_hidden = 0
                    AND (intent = 'deadline' OR due_at IS NOT NULL AND due_at != '')
                """
                params: list[object] = [user_email]
                if source_account:
                    q += " AND source_account = ?"
                    params.append(source_account)
                q += " ORDER BY urgency DESC, COALESCE(received_at, created_at) DESC LIMIT ?"
                params.append(limit)
                deadline_rows = connection.execute(q, params).fetchall()
            rows.extend(self._deserialize_row(r) for r in deadline_rows if r)
        if action_type in ("waiting_on_me", "this_week", "find_topic"):
            with self._connect() as connection:
                q = """
                    SELECT * FROM emails
                    WHERE user_email = ? AND is_hidden = 0 AND intent = 'i_owe'
                """
                params = [user_email]
                if source_account:
                    q += " AND source_account = ?"
                    params.append(source_account)
                q += " ORDER BY urgency DESC, COALESCE(received_at, created_at) DESC LIMIT ?"
                params.append(limit)
                owe_rows = connection.execute(q, params).fetchall()
            rows.extend(self._deserialize_row(r) for r in owe_rows if r)
        seen: set[str] = set()
        out: list[dict] = []
        for row in rows:
            if not row:
                continue
            eid = row.get("email_id")
            if eid and eid not in seen:
                seen.add(eid)
                out.append(row)
        return out[:limit]

    def upsert_assignment_items(self, user_email: str, items: list[dict]) -> int:
        saved = 0
        with self._connect() as connection:
            for item in items:
                eid = str(item.get("email_id") or "").strip()
                title = sanitize_action_title(str(item.get("title") or item.get("reason") or ""))
                if not eid or not title:
                    continue
                due = str(item.get("due_at") or item.get("due_date") or "")[:10] or None
                connection.execute(
                    """
                    INSERT OR IGNORE INTO assignment_items (user_email, email_id, title, due_at, status, source)
                    VALUES (?, ?, ?, ?, 'open', 'ai')
                    """,
                    (user_email, eid, title, due),
                )
                saved += 1
        return saved

    def list_assignment_board(self, user_email: str, *, include_done: bool = False) -> list[dict]:
        """Merge AI items with due-date / school / deadline emails."""
        items: list[dict] = []
        with self._connect() as connection:
            status_clause = "" if include_done else " AND status = 'open'"
            rows = connection.execute(
                f"""
                SELECT assignment_items.*, emails.subject, emails.sender, emails.source_account,
                       emails.thread_id, emails.message_id, emails.received_at
                FROM assignment_items
                LEFT JOIN emails ON emails.email_id = assignment_items.email_id
                WHERE assignment_items.user_email = ?{status_clause}
                ORDER BY COALESCE(assignment_items.due_at, '9999-12-31'), assignment_items.updated_at DESC
                """,
                (user_email,),
            ).fetchall()
            for row in rows:
                item = dict(row)
                item["title"] = sanitize_action_title(item.get("title") or "")
                items.append(item)

        school_tag = next(
            (t for t in self.list_tags(user_email) if (t.get("name") or "").lower() == "school"),
            None,
        )
        seen_ids = {i.get("email_id") for i in items}
        extra: list[dict] = []
        if school_tag:
            for email in self.list_emails(
                limit=60,
                user_email=user_email,
                tag_filter=school_tag["id"],
                sort="urgency",
            ):
                if email.get("due_at") or email.get("intent") == "deadline":
                    eid = email.get("email_id")
                    if eid and eid not in seen_ids:
                        seen_ids.add(eid)
                        extra.append(
                            {
                                "id": None,
                                "email_id": eid,
                                "title": sanitize_action_title(
                                    email.get("line_summary") or email.get("subject") or "Assignment"
                                ),
                                "due_at": email.get("due_at"),
                                "status": "open",
                                "source": "email",
                                "subject": email.get("subject"),
                                "sender": email.get("sender"),
                                "source_account": email.get("source_account"),
                                "thread_id": email.get("thread_id"),
                                "message_id": email.get("message_id"),
                                "received_at": email.get("received_at"),
                            }
                        )
        items.extend(extra)
        items.sort(
            key=lambda r: (r.get("due_at") or "9999-12-31", r.get("received_at") or ""),
        )
        return items

    def set_assignment_status(self, user_email: str, item_id: int, status: str) -> bool:
        with self._connect() as connection:
            cur = connection.execute(
                """
                UPDATE assignment_items SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_email = ?
                """,
                (status, item_id, user_email),
            )
            return cur.rowcount > 0

    def gemini_tokens_used_today(self, user_email: str) -> int:
        from .token_budget import GeminiQuotaTracker, BudgetLimits

        tracker = GeminiQuotaTracker(self, user_email, BudgetLimits.from_env())
        return tracker.tokens_used_today()