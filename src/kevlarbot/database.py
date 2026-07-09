import json
import time
from typing import List, Dict, Tuple, Optional, Any

import aiosqlite

from kevlarbot.config import get_fernet, logger
from kevlarbot.providers import DEFAULT_PERSONA


class MimoDB:
    def __init__(self, db_name: str = "kevlarbot.db"):
        self.db_name = db_name
        self.db: Optional[aiosqlite.Connection] = None
        self._fernet = get_fernet()

    async def connect(self):
        self.db = await aiosqlite.connect(self.db_name)
        await self._init_tables()

    async def close(self):
        if self.db:
            await self.db.close()

    async def _init_tables(self):
        await self.db.execute('''
            CREATE TABLE IF NOT EXISTS users_v3 (
                chat_id INTEGER PRIMARY KEY,
                history TEXT,
                active_model TEXT,
                custom_keys TEXT,
                persona TEXT DEFAULT 'default',
                is_allowed INTEGER DEFAULT 0,
                username TEXT,
                display_name TEXT,
                joined_at REAL,
                last_updated REAL
            )
        ''')
        cursor = await self.db.execute("PRAGMA table_info(users_v3)")
        cols = {row[1] for row in await cursor.fetchall()}
        if "persona" not in cols:
            await self.db.execute("ALTER TABLE users_v3 ADD COLUMN persona TEXT DEFAULT 'default'")
        if "joined_at" not in cols:
            await self.db.execute("ALTER TABLE users_v3 ADD COLUMN joined_at REAL")
        if "is_allowed" not in cols:
            await self.db.execute("ALTER TABLE users_v3 ADD COLUMN is_allowed INTEGER DEFAULT 0")
        if "username" not in cols:
            await self.db.execute("ALTER TABLE users_v3 ADD COLUMN username TEXT")
        if "display_name" not in cols:
            await self.db.execute("ALTER TABLE users_v3 ADD COLUMN display_name TEXT")
        await self.db.commit()

    def _encrypt_keys(self, keys: Dict[str, str]) -> str:
        if not keys:
            return "{}"
        return json.dumps({k: self._fernet.encrypt(v.encode()).decode() for k, v in keys.items()})

    def _decrypt_keys(self, raw: str) -> Dict[str, str]:
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return {k: self._fernet.decrypt(v.encode()).decode() for k, v in data.items()}
        except Exception:
            return json.loads(raw) if raw else {}

    async def get_user_data(self, chat_id: int) -> Tuple[List[Dict[str, str]], str, Dict[str, str], str]:
        async with self.db.execute(
            "SELECT history, active_model, custom_keys, persona FROM users_v3 WHERE chat_id = ?", (chat_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                history = json.loads(row[0]) if row[0] else []
                active_model = row[1] or "mimo"
                custom_keys = self._decrypt_keys(row[2]) if row[2] else {}
                persona = row[3] or DEFAULT_PERSONA
                return history, active_model, custom_keys, persona
            return [], "mimo", {}, DEFAULT_PERSONA

    async def is_user_allowed(self, chat_id: int) -> bool:
        async with self.db.execute(
            "SELECT is_allowed FROM users_v3 WHERE chat_id = ?", (chat_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return bool(row[0])
            return False

    async def user_exists(self, chat_id: int) -> bool:
        async with self.db.execute(
            "SELECT 1 FROM users_v3 WHERE chat_id = ?", (chat_id,)
        ) as cursor:
            return await cursor.fetchone() is not None

    async def set_user_allowed(self, chat_id: int, allowed: bool):
        await self.db.execute(
            "UPDATE users_v3 SET is_allowed = ? WHERE chat_id = ?",
            (1 if allowed else 0, chat_id)
        )
        await self.db.commit()

    async def get_user_by_username(self, username: str) -> Optional[int]:
        clean = username.lstrip("@").lower()
        async with self.db.execute(
            "SELECT chat_id FROM users_v3 WHERE LOWER(username) = ?", (clean,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

    async def get_user_by_id(self, chat_id: int) -> bool:
        async with self.db.execute(
            "SELECT 1 FROM users_v3 WHERE chat_id = ?", (chat_id,)
        ) as cursor:
            return await cursor.fetchone() is not None

    async def get_all_users(self) -> List[Dict[str, Any]]:
        async with self.db.execute(
            "SELECT chat_id, username, display_name, is_allowed, joined_at FROM users_v3 ORDER BY joined_at"
        ) as cursor:
            rows = await cursor.fetchall()
            return [
                {
                    "chat_id": row[0],
                    "username": row[1],
                    "display_name": row[2],
                    "is_allowed": bool(row[3]),
                    "joined_at": row[4],
                }
                for row in rows
            ]

    async def save_user_data(self, chat_id: int, history: List[Dict[str, str]], active_model: str,
                              custom_keys: Dict[str, str], persona: str,
                              username: Optional[str] = None, display_name: Optional[str] = None):
        now = time.time()
        await self.db.execute('''
            INSERT INTO users_v3 (chat_id, history, active_model, custom_keys, persona, username, display_name, joined_at, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
            history=excluded.history,
            active_model=excluded.active_model,
            custom_keys=excluded.custom_keys,
            persona=excluded.persona,
            username=COALESCE(excluded.username, users_v3.username),
            display_name=COALESCE(excluded.display_name, users_v3.display_name),
            last_updated=excluded.last_updated
        ''', (chat_id, json.dumps(history), active_model, self._encrypt_keys(custom_keys), persona,
              username, display_name, now, now))
        await self.db.commit()

    async def clear_history(self, chat_id: int):
        history, active_model, custom_keys, persona = await self.get_user_data(chat_id)
        await self.save_user_data(chat_id, [], active_model, custom_keys, persona)

    async def all_chat_ids(self) -> List[int]:
        async with self.db.execute("SELECT chat_id FROM users_v3") as cursor:
            return [row[0] for row in await cursor.fetchall()]

    async def user_count(self) -> int:
        async with self.db.execute("SELECT COUNT(*) FROM users_v3") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0
