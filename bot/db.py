from __future__ import annotations

from pathlib import Path
from typing import Any
import aiosqlite


class Database:
    def __init__(self, path: str):
        self.path = Path(path)

    async def init(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self.path.as_posix()) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS plays (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER,
                    channel_id INTEGER,
                    guild_id INTEGER,
                    author_id INTEGER,
                    channel_name TEXT,
                    tier TEXT,
                    play_type TEXT,
                    content TEXT,
                    odds INTEGER,
                    units REAL,
                    result TEXT,
                    profit REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    graded_at TIMESTAMP
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS tails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    play_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            await db.commit()

    async def get_setting(self, key: str, default: str | None = None) -> str | None:
        async with aiosqlite.connect(self.path.as_posix()) as db:
            cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = await cur.fetchone()
            return row[0] if row else default

    async def set_setting(self, key: str, value: str):
        async with aiosqlite.connect(self.path.as_posix()) as db:
            await db.execute("""
                INSERT INTO settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (key, value))
            await db.commit()

    async def create_play(self, data: dict[str, Any]) -> int:
        async with aiosqlite.connect(self.path.as_posix()) as db:
            cur = await db.execute("""
                INSERT INTO plays (
                    message_id, channel_id, guild_id, author_id, channel_name,
                    tier, play_type, content, odds, units, result, profit
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0)
            """, (
                data["message_id"],
                data["channel_id"],
                data["guild_id"],
                data["author_id"],
                data["channel_name"],
                data["tier"],
                data["play_type"],
                data["content"],
                data["odds"],
                data["units"],
            ))
            await db.commit()
            return cur.lastrowid

    async def get_play(self, play_id: int):
        async with aiosqlite.connect(self.path.as_posix()) as db:
            cur = await db.execute("SELECT * FROM plays WHERE id = ?", (play_id,))
            return await cur.fetchone()

    async def get_play_by_message(self, message_id: int):
        async with aiosqlite.connect(self.path.as_posix()) as db:
            cur = await db.execute("SELECT * FROM plays WHERE message_id = ?", (message_id,))
            return await cur.fetchone()

    async def pending_plays(self):
        async with aiosqlite.connect(self.path.as_posix()) as db:
            cur = await db.execute("""
                SELECT * FROM plays
                WHERE result = 'PENDING'
                ORDER BY id DESC
            """)
            return await cur.fetchall()

    async def grade_play(self, play_id: int, result: str, profit: float):
        async with aiosqlite.connect(self.path.as_posix()) as db:
            await db.execute("""
                UPDATE plays
                SET result = ?, profit = ?, graded_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (result, profit, play_id))
            await db.commit()

    async def stats(self, scope: str = "ALL", days: int | None = None) -> dict[str, Any]:
        query = """
            SELECT play_type, result, COUNT(*), COALESCE(SUM(profit), 0)
            FROM plays
            WHERE result != 'PENDING'
        """
        params: list[Any] = []

        if scope in ("VIP", "PUB"):
            query += " AND tier = ?"
            params.append(scope)

        if days is not None:
            query += " AND datetime(created_at) >= datetime('now', ?)"
            params.append(f"-{days} days")

        query += " GROUP BY play_type, result"

        wins = losses = voids = cashouts = 0
        units = 0.0
        breakdown: dict[str, dict[str, int]] = {}

        async with aiosqlite.connect(self.path.as_posix()) as db:
            cur = await db.execute(query, tuple(params))
            rows = await cur.fetchall()

        graded_count = 0
        for play_type, result, count, total_profit in rows:
            graded_count += count
            units += float(total_profit or 0)

            if play_type not in breakdown:
                breakdown[play_type] = {}

            breakdown[play_type][result] = count

            if result == "WIN":
                wins += count
            elif result == "LOSS":
                losses += count
            elif result == "VOID":
                voids += count
            elif result == "CASHOUT":
                cashouts += count

        win_rate = round((wins / max(wins + losses, 1)) * 100, 1)

        return {
            "wins": wins,
            "losses": losses,
            "voids": voids,
            "cashouts": cashouts,
            "units": round(units, 2),
            "win_rate": win_rate,
            "graded_count": graded_count,
            "breakdown": breakdown,
        }

    async def tail_leaderboard(self):
        async with aiosqlite.connect(self.path.as_posix()) as db:
            cur = await db.execute("""
                SELECT
                    user_id,
                    COUNT(*) as tails,
                    SUM(CASE WHEN status = 'WIN' THEN 1 ELSE 0 END) as wins,
                    SUM(CASE WHEN status = 'LOSS' THEN 1 ELSE 0 END) as losses
                FROM tails
                GROUP BY user_id
                ORDER BY tails DESC, wins DESC
                LIMIT 25
            """)
            return await cur.fetchall()
