from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

try:
    from libsql_client import Client
except ImportError:
    Client = None


class DBManager:
    def __init__(self, db_name: str = "quran_bot.db"):
        self.db_url = os.getenv("DATABASE_URL")
        self.db_auth_token = os.getenv("DATABASE_AUTH_TOKEN")
        self._libsql_client = None

        if self.db_url and self.db_auth_token and Client:
            self._libsql_client = Client(self.db_url, auth_token=self.db_auth_token)
            self.mode = "turso"
        else:
            data_dir = Path.home() / "QuranBotData"
            data_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = data_dir / db_name
            self.mode = "sqlite"

        self.create_tables()

    def _execute(self, query: str, params=()):
        if self.mode == "turso":
            return self._libsql_client.execute(query, params)
        else:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(query, params)
                rows = cur.fetchall()
                conn.commit()
                return rows

    def _get_rows(self, result):
        if self.mode == "turso":
            if not result.rows:
                return []
            return [dict(zip(result.columns, row)) for row in result.rows]
        else:
            return [dict(row) for row in result]

    def _get_first(self, result):
        if self.mode == "turso":
            if not result.rows:
                return None
            return dict(zip(result.columns, result.rows[0]))
        else:
            if not result:
                return None
            return dict(result[0])

    def create_tables(self) -> None:
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                daily_goal INTEGER NOT NULL DEFAULT 1,
                current_page INTEGER NOT NULL DEFAULT 1,
                send_time TEXT NOT NULL DEFAULT '08:00',
                is_active INTEGER NOT NULL DEFAULT 1,
                last_sent_date TEXT,
                completed_khatmas INTEGER NOT NULL DEFAULT 0,
                language TEXT NOT NULL DEFAULT 'ar',
                khatma_read_count INTEGER NOT NULL DEFAULT 0,
                is_setup INTEGER NOT NULL DEFAULT 0,
                khatma_number INTEGER NOT NULL DEFAULT 0,
                chat_type TEXT NOT NULL DEFAULT 'private',
                send_images INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        for col, definition in [
            ("completed_khatmas", "INTEGER NOT NULL DEFAULT 0"),
            ("language", "TEXT NOT NULL DEFAULT 'ar'"),
            ("khatma_read_count", "INTEGER NOT NULL DEFAULT 0"),
            ("is_setup", "INTEGER NOT NULL DEFAULT 0"),
            ("khatma_number", "INTEGER NOT NULL DEFAULT 0"),
            ("chat_type", "TEXT NOT NULL DEFAULT 'private'"),
            ("send_images", "INTEGER NOT NULL DEFAULT 1"),
        ]:
            try:
                self._execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            except Exception:
                pass

    def add_user(self, user_id: int, username: Optional[str], chat_type: str = "private") -> None:
        self._execute(
            """
            INSERT INTO users (user_id, username, chat_type)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                is_active = 1
            """,
            (user_id, username, chat_type),
        )

    def update_settings(
        self,
        user_id: int,
        goal: Optional[int] = None,
        send_time: Optional[str] = None,
        page: Optional[int] = None,
        is_active: Optional[bool] = None,
        last_sent_date: Optional[str] = None,
        language: Optional[str] = None,
        is_setup: Optional[bool] = None,
        khatma_number: Optional[int] = None,
        chat_type: Optional[str] = None,
        send_images: Optional[bool] = None,
    ) -> None:
        updates = []
        params = []

        if goal is not None:
            updates.append("daily_goal = ?")
            params.append(goal)
        if send_time is not None:
            updates.append("send_time = ?")
            params.append(send_time)
        if page is not None:
            updates.append("current_page = ?")
            params.append(page)
        if is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if is_active else 0)
        if last_sent_date is not None:
            updates.append("last_sent_date = ?")
            params.append(last_sent_date)
        if language is not None:
            updates.append("language = ?")
            params.append(language)
        if is_setup is not None:
            updates.append("is_setup = ?")
            params.append(1 if is_setup else 0)
        if khatma_number is not None:
            updates.append("khatma_number = ?")
            params.append(khatma_number)
        if chat_type is not None:
            updates.append("chat_type = ?")
            params.append(chat_type)
        if send_images is not None:
            updates.append("send_images = ?")
            params.append(1 if send_images else 0)

        if not updates:
            return

        params.append(user_id)
        self._execute(
            f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?", params
        )

    def get_user(self, user_id: int) -> dict | None:
        result = self._execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        )
        return self._get_first(result)

    def get_all_active_users(self, private_only: bool = False) -> list[dict]:
        if private_only:
            result = self._execute("SELECT * FROM users WHERE is_active = 1 AND chat_type = 'private'")
        else:
            result = self._execute("SELECT * FROM users WHERE is_active = 1")
        return self._get_rows(result)

    def get_users_due(
        self, current_time: str, pdf_prepare_time: str, today: str
    ) -> list[dict]:
        result = self._execute(
            """
            SELECT * FROM users
            WHERE is_active = 1
              AND is_setup = 1
              AND (last_sent_date IS NULL OR last_sent_date != ?)
              AND (
                    send_time <= ?
                    OR (daily_goal > 10 AND send_time <= ?)
              )
            """,
            (today, current_time, pdf_prepare_time),
        )
        return self._get_rows(result)

    def clear_last_sent_date(self, user_id: int) -> None:
        self._execute(
            "UPDATE users SET last_sent_date = NULL WHERE user_id = ?", (user_id,)
        )

    def increment_completed_khatmas(self, user_id: int) -> None:
        self._execute(
            """
            UPDATE users
            SET completed_khatmas = completed_khatmas + 1
            WHERE user_id = ?
            """,
            (user_id,),
        )

    def count_active_users(self) -> int:
        result = self._execute(
            "SELECT COUNT(*) AS total FROM users WHERE is_active = 1"
        )
        return int(self._get_first(result)["total"])

    def count_total_completed_khatmas(self) -> int:
        result = self._execute(
            "SELECT COALESCE(SUM(completed_khatmas), 0) AS total FROM users"
        )
        return int(self._get_first(result)["total"])

    def increment_khatma_read_count(self, user_id: int) -> None:
        self._execute(
            """
            UPDATE users
            SET khatma_read_count = khatma_read_count + 1
            WHERE user_id = ?
            """,
            (user_id,),
        )

    def count_total_khatma_readers(self) -> int:
        result = self._execute(
            "SELECT COALESCE(SUM(khatma_read_count), 0) AS total FROM users"
        )
        return int(self._get_first(result)["total"])

    def get_khatma_number(self, user_id: int) -> int:
        result = self._execute(
            "SELECT khatma_number FROM users WHERE user_id = ?", (user_id,)
        )
        row = self._get_first(result)
        return int(row["khatma_number"]) if row else 0
