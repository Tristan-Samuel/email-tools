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
                    source_account TEXT NOT NULL DEFAULT '',
                    ai_analyzed INTEGER NOT NULL DEFAULT 0,
                    is_hidden INTEGER NOT NULL DEFAULT 0
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
            if "ai_analyzed" not in columns:
                connection.execute("ALTER TABLE emails ADD COLUMN ai_analyzed INTEGER NOT NULL DEFAULT 0")
            if "is_hidden" not in columns:
                connection.execute("ALTER TABLE emails ADD COLUMN is_hidden INTEGER NOT NULL DEFAULT 0")

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
                        bullet_summary=CASE WHEN excluded.ai_analyzed=1 THEN excluded.bullet_summary ELSE emails.bullet_summary END,
                        ai_analyzed=MAX(emails.ai_analyzed, excluded.ai_analyzed),
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
        sender_filter: str | None = None,
        recipient_filter: str | None = None,
        subject_filter: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        exclude_hidden: bool = True,
        only_hidden: bool = False,
        tag_filter: int | None = None,
        sort: str = "date_desc",
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
        query += f" ORDER BY {_order} LIMIT ?"
        params.append(limit)

        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()

        return [self._deserialize_row(row) for row in rows]

    def search(
        self,
        search_term: str,
        limit: int = 100,
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

        fts_clause = (" AND " + " AND ".join(fts_extra)) if fts_extra else ""
        like_clause = (" AND " + " AND ".join(like_extra)) if like_extra else ""

        _order = {
            "date_asc":  "COALESCE(received_at, created_at) ASC",
            "priority":  "priority_score DESC, COALESCE(received_at, created_at) DESC",
        }.get(sort, "COALESCE(received_at, created_at) DESC")
        _fts_order = _order.replace("received_at", "emails.received_at").replace("created_at", "emails.created_at")

        with self._connect() as connection:
            wildcard = f"%{search_term}%"

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
                            LIMIT ?
                            """,
                            (search_term, user_email, *fts_params, limit),
                        ).fetchall()
                    else:
                        rows = connection.execute(
                            f"""
                            SELECT emails.*
                            FROM email_search
                            JOIN emails ON emails.email_id = email_search.email_id
                            WHERE email_search MATCH ?{fts_clause}
                            ORDER BY {_fts_order}
                            LIMIT ?
                            """,
                            (search_term, *fts_params, limit),
                        ).fetchall()
                except sqlite3.OperationalError:
                    if user_email:
                        rows = connection.execute(
                            f"""
                            SELECT * FROM emails
                            WHERE search_blob LIKE ? AND user_email = ?{like_clause}
                            ORDER BY {_order}
                            LIMIT ?
                            """,
                            (wildcard, user_email, *like_params, limit),
                        ).fetchall()
                    else:
                        rows = connection.execute(
                            f"""
                            SELECT * FROM emails
                            WHERE search_blob LIKE ?{like_clause}
                            ORDER BY {_order}
                            LIMIT ?
                            """,
                            (wildcard, *like_params, limit),
                        ).fetchall()
            else:
                if user_email:
                    rows = connection.execute(
                        f"""
                        SELECT * FROM emails
                        WHERE search_blob LIKE ? AND user_email = ?{like_clause}
                        ORDER BY {_order}
                        LIMIT ?
                        """,
                        (wildcard, user_email, *like_params, limit),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        f"""
                        SELECT * FROM emails
                        WHERE search_blob LIKE ?{like_clause}
                        ORDER BY {_order}
                        LIMIT ?
                        """,
                        (wildcard, *like_params, limit),
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

    def update_email_summary(self, email_id: str, user_email: str, bullet_summary: list[str]) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE emails SET bullet_summary = ?, ai_analyzed = 1 WHERE email_id = ? AND user_email = ?",
                (json.dumps(bullet_summary), email_id, user_email),
            )
            if self.fts_enabled:
                connection.execute(
                    "UPDATE email_search SET bullet_summary = ? WHERE email_id = ?",
                    (" ".join(bullet_summary), email_id),
                )

    def set_email_hidden(self, email_id: str, user_email: str, hidden: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE emails SET is_hidden = ? WHERE email_id = ? AND user_email = ?",
                (1 if hidden else 0, email_id, user_email),
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
            result = []
            for tag in tags:
                tag_dict = dict(tag)
                rules = connection.execute(
                    "SELECT * FROM tag_rules WHERE tag_id = ?",
                    (tag_dict["id"],),
                ).fetchall()
                tag_dict["rules"] = [dict(r) for r in rules]
                tag_dict["email_count"] = connection.execute(
                    "SELECT COUNT(*) FROM email_tags WHERE tag_id = ?",
                    (tag_dict["id"],),
                ).fetchone()[0]
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
        manual_tags = [t for t in tags if not t["use_ai"] or t["rules"]]
        if not manual_tags:
            return 0

        emails = self.list_emails(user_email=user_email, limit=10000, exclude_hidden=False)
        updated = 0
        with self._connect() as connection:
            for email in emails:
                matched_ids = self.apply_manual_tags_to_email(email, manual_tags)
                existing = {r[0] for r in connection.execute(
                    "SELECT tag_id FROM email_tags WHERE email_id = ?",
                    (email["email_id"],),
                ).fetchall()}
                for tag_id in matched_ids:
                    if tag_id not in existing:
                        connection.execute(
                            "INSERT OR IGNORE INTO email_tags (email_id, tag_id) VALUES (?, ?)",
                            (email["email_id"], tag_id),
                        )
                        updated += 1
                # Auto-hide if tag has hide_matching
                hide_tag_ids = {t["id"] for t in manual_tags if t["hide_matching"]}
                if any(tid in hide_tag_ids for tid in matched_ids):
                    connection.execute(
                        "UPDATE emails SET is_hidden = 1 WHERE email_id = ? AND user_email = ?",
                        (email["email_id"], user_email),
                    )
        return updated