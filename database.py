from __future__ import annotations

import asyncio
import json as json_mod
import logging
import os
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DBManager:
    def __init__(self, db_name: str = "quran_bot.db"):
        data_dir = Path.home() / "QuranBotData"
        data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = data_dir / db_name

        self.db_url = os.getenv("DATABASE_URL")
        self.db_token = os.getenv("DATABASE_AUTH_TOKEN")
        self._turso_client = None

        if self.db_url and self.db_token:
            try:
                from libsql_client import create_client
                self._turso_client = create_client(self.db_url, auth_token=self.db_token)
                logger.info("Connected to Turso database")
            except Exception as e:
                logger.warning("Failed to connect to Turso: %s. Using SQLite.", e)

        if not self._turso_client:
            self.create_tables_sync()

    def _is_turso(self) -> bool:
        return self._turso_client is not None

    def _execute_sync(self, query: str, params=()) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(query, params)
            rows = [dict(row) for row in cur.fetchall()]
            conn.commit()
            return rows

    async def _execute_async(self, query: str, params=()) -> list[dict]:
        result_set = await self._turso_client.execute(query, params)
        return [dict(zip(result_set.columns, row.values)) for row in result_set.rows]

    def _execute(self, query: str, params=()) -> list[dict]:
        if self._is_turso():
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._execute_async(query, params))
        return self._execute_sync(query, params)

    async def _execute_awaitable(self, query: str, params=()) -> list[dict]:
        if self._is_turso():
            return await self._execute_async(query, params)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._execute_sync, query, params)

    def create_tables_sync(self) -> None:
        self._execute_sync(
            """CREATE TABLE IF NOT EXISTS users (
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
                send_images INTEGER NOT NULL DEFAULT 1,
                khatma_unread INTEGER NOT NULL DEFAULT 0
            )"""
        )
        for col, definition in [
            ("completed_khatmas", "INTEGER NOT NULL DEFAULT 0"),
            ("language", "TEXT NOT NULL DEFAULT 'ar'"),
            ("khatma_read_count", "INTEGER NOT NULL DEFAULT 0"),
            ("is_setup", "INTEGER NOT NULL DEFAULT 0"),
            ("khatma_number", "INTEGER NOT NULL DEFAULT 0"),
            ("chat_type", "TEXT NOT NULL DEFAULT 'private'"),
            ("send_images", "INTEGER NOT NULL DEFAULT 1"),
            ("khatma_unread", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            try:
                self._execute_sync(f"ALTER TABLE users ADD COLUMN {col} {definition}")
            except Exception:
                pass

    async def create_tables(self) -> None:
        if self._is_turso():
            await self._execute_awaitable(
                """CREATE TABLE IF NOT EXISTS users (
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
                    send_images INTEGER NOT NULL DEFAULT 1,
                    khatma_unread INTEGER NOT NULL DEFAULT 0
                )"""
            )
            for col, definition in [
                ("completed_khatmas", "INTEGER NOT NULL DEFAULT 0"),
                ("language", "TEXT NOT NULL DEFAULT 'ar'"),
                ("khatma_read_count", "INTEGER NOT NULL DEFAULT 0"),
                ("is_setup", "INTEGER NOT NULL DEFAULT 0"),
                ("khatma_number", "INTEGER NOT NULL DEFAULT 0"),
                ("chat_type", "TEXT NOT NULL DEFAULT 'private'"),
                ("send_images", "INTEGER NOT NULL DEFAULT 1"),
                ("khatma_unread", "INTEGER NOT NULL DEFAULT 0"),
            ]:
                try:
                    await self._execute_awaitable(f"ALTER TABLE users ADD COLUMN {col} {definition}")
                except Exception:
                    pass
        else:
            self.create_tables_sync()

    def add_user(self, user_id: int, username: Optional[str], chat_type: str = "private") -> None:
        self._execute(
            "INSERT INTO users (user_id, username, chat_type) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET username = excluded.username, is_active = 1",
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
        completed_khatmas: Optional[int] = None,
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
        if completed_khatmas is not None:
            updates.append("completed_khatmas = ?")
            params.append(completed_khatmas)
        if not updates:
            return
        params.append(user_id)
        self._execute(f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?", params)

    def get_user(self, user_id: int) -> dict | None:
        result = self._execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return result[0] if result else None

    def get_all_active_users(self, private_only: bool = False) -> list[dict]:
        if private_only:
            return self._execute("SELECT * FROM users WHERE is_active = 1 AND chat_type = 'private'")
        return self._execute("SELECT * FROM users WHERE is_active = 1")

    def get_users_due(self, current_time: str, pdf_prepare_time: str, today: str) -> list[dict]:
        return self._execute(
            """SELECT * FROM users
            WHERE is_active = 1 AND is_setup = 1
            AND (last_sent_date IS NULL OR last_sent_date != ?)
            AND (send_time <= ? OR (daily_goal > 10 AND send_time <= ?))""",
            (today, current_time, pdf_prepare_time),
        )

    def clear_last_sent_date(self, user_id: int) -> None:
        self._execute("UPDATE users SET last_sent_date = NULL WHERE user_id = ?", (user_id,))

    def increment_completed_khatmas(self, user_id: int) -> None:
        self._execute("UPDATE users SET completed_khatmas = completed_khatmas + 1 WHERE user_id = ?", (user_id,))

    def count_active_users(self) -> int:
        result = self._execute("SELECT COUNT(*) AS total FROM users WHERE is_active = 1")
        return int(result[0]["total"])

    def count_total_completed_khatmas(self) -> int:
        result = self._execute("SELECT COALESCE(SUM(completed_khatmas), 0) AS total FROM users")
        return int(result[0]["total"])

    def increment_khatma_read_count(self, user_id: int) -> None:
        self._execute("UPDATE users SET khatma_read_count = khatma_read_count + 1 WHERE user_id = ?", (user_id,))

    def increment_khatma_unread(self, user_id: int) -> None:
        self._execute("UPDATE users SET khatma_unread = khatma_unread + 1 WHERE user_id = ?", (user_id,))

    def count_total_khatma_readers(self) -> int:
        result = self._execute("SELECT COALESCE(SUM(khatma_read_count), 0) AS total FROM users")
        return int(result[0]["total"])

    def get_khatma_number(self, user_id: int) -> int:
        result = self._execute("SELECT khatma_number FROM users WHERE user_id = ?", (user_id,))
        if not result:
            return 0
        return int(result[0]["khatma_number"])

    def export_json(self) -> str:
        result = self._execute("SELECT * FROM users")
        return json_mod.dumps(result, ensure_ascii=False, indent=2)

    def import_json(self, json_data: str) -> int:
        users = json_mod.loads(json_data)
        if not users:
            return 0
        count = 0
        for user in users:
            self._execute(
                """INSERT INTO users (user_id, username, daily_goal, current_page, send_time,
                    is_active, last_sent_date, completed_khatmas, language,
                    khatma_read_count, is_setup, khatma_number, chat_type, send_images)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    daily_goal = excluded.daily_goal,
                    current_page = excluded.current_page,
                    send_time = excluded.send_time,
                    is_active = excluded.is_active,
                    last_sent_date = excluded.last_sent_date,
                    completed_khatmas = excluded.completed_khatmas,
                    language = excluded.language,
                    khatma_read_count = excluded.khatma_read_count,
                    is_setup = excluded.is_setup,
                    khatma_number = excluded.khatma_number,
                    chat_type = excluded.chat_type,
                    send_images = excluded.send_images""",
                (
                    user["user_id"],
                    user.get("username"),
                    user.get("daily_goal", 1),
                    user.get("current_page", 1),
                    user.get("send_time", "08:00"),
                    user.get("is_active", 1),
                    user.get("last_sent_date"),
                    user.get("completed_khatmas", 0),
                    user.get("language", "ar"),
                    user.get("khatma_read_count", 0),
                    user.get("is_setup", 0),
                    user.get("khatma_number", 0),
                    user.get("chat_type", "private"),
                    user.get("send_images", 1),
                ),
            )
            count += 1
        return count
