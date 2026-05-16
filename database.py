import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional


class DBManager:
    def __init__(self, db_name: str = "quran_bot.db"):
        self.db_path = Path(db_name)
        self.create_tables()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create_tables(self) -> None:
        with self.connect() as conn:
            conn.execute(
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
                    language TEXT NOT NULL DEFAULT 'ar'
                )
                """
            )
            self._ensure_column(
                conn, "users", "completed_khatmas", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(conn, "users", "language", "TEXT NOT NULL DEFAULT 'ar'")

    def _ensure_column(
        self, conn: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def add_user(self, user_id: int, username: Optional[str]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, username)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    is_active = 1
                """,
                (user_id, username),
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

        if not updates:
            return

        params.append(user_id)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?", params
            )

    def get_user(self, user_id: int):
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ).fetchone()

    def get_all_active_users(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM users WHERE is_active = 1").fetchall()

    def get_users_due(
        self, current_time: str, pdf_prepare_time: str, today: str
    ) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT * FROM users
                WHERE is_active = 1
                  AND (last_sent_date IS NULL OR last_sent_date != ?)
                  AND (
                        send_time <= ?
                        OR (daily_goal > 10 AND send_time <= ?)
                  )
                """,
                (today, current_time, pdf_prepare_time),
            ).fetchall()

    def clear_last_sent_date(self, user_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE users SET last_sent_date = NULL WHERE user_id = ?", (user_id,)
            )

    def increment_completed_khatmas(self, user_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET completed_khatmas = completed_khatmas + 1
                WHERE user_id = ?
                """,
                (user_id,),
            )

    def count_active_users(self) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM users WHERE is_active = 1"
            ).fetchone()
            return int(row["total"])

    def count_total_completed_khatmas(self) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(completed_khatmas), 0) AS total FROM users"
            ).fetchone()
            return int(row["total"])
