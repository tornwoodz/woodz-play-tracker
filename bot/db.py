from __future__ import annotations

import aiosqlite
from typing import Any


class Database:
    def __init__(self, path: str = "data/tracker.db") -> None:
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS plays (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    author_id INTEGER NOT NULL,
                    channel_name TEXT NOT NULL,
                    tier TEXT NOT NULL,
                    play_type TEXT NOT NULL,
                    content TEXT,
                    odds INTEGER,
                    units REAL NOT NULL DEFAULT 1.0,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    profit_units REAL NOT NULL DEFAULT 0,
                    cashout_units REAL,
                    tailed_count INTEGER NOT NULL DEFAULT 0,
                    watched_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    graded_at TEXT
                );

                CREATE TABLE IF NOT EXISTS tails (
                    play_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(play_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            await db.commit()

    async def set_setting(self, key: str, value: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            await db.commit()

    async def get_setting(self, key: str, default: str | None = None) -> str | None:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
                row = await cur.fetchone()
                return row[0] if row else default

    async def create_play(self, payload: dict[str, Any]) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                INSERT INTO plays (
                    message_id, channel_id, guild_id, author_id, channel_name, tier, play_type,
                    content, odds, units, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
                """,
                (
                    payload["message_id"], payload["channel_id"], payload["guild_id"], payload["author_id"],
                    payload["channel_name"], payload["tier"], payload["play_type"], payload.get("content", ""),
                    payload.get("odds"), payload.get("units", 1.0),
                ),
            )
            await db.commit()
            return cur.lastrowid

    async def get_play(self, play_id: int) -> tuple | None:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT * FROM plays WHERE id = ?", (play_id,)) as cur:
                return await cur.fetchone()

    async def get_play_by_message(self, message_id: int) -> tuple | None:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT * FROM plays WHERE message_id = ?", (message_id,)) as cur:
                return await cur.fetchone()

    async def pending_plays(self) -> list[tuple]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT * FROM plays WHERE status='PENDING' ORDER BY id DESC") as cur:
                return await cur.fetchall()

    async def grade_play(self, play_id: int, status: str, profit_units: float) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE plays SET status=?, profit_units=?, graded_at=CURRENT_TIMESTAMP WHERE id=?",
                (status, profit_units, play_id),
            )
            await db.commit()

    async def add_tail(self, play_id: int, user_id: int, action: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO tails (play_id, user_id, action) VALUES (?, ?, ?) ON CONFLICT(play_id, user_id) DO UPDATE SET action=excluded.action",
                (play_id, user_id, action),
            )
            await db.execute(
                "UPDATE plays SET tailed_count=(SELECT COUNT(*) FROM tails WHERE play_id=? AND action='TAIL'), watched_count=(SELECT COUNT(*) FROM tails WHERE play_id=? AND action='WATCH') WHERE id=?",
                (play_id, play_id, play_id),
            )
            await db.commit()

    async def stats(self, scope: str = "ALL", days: int | None = None) -> dict[str, Any]:
        where = []
        params: list[Any] = []
        if scope in {"VIP", "PUB"}:
            where.append("tier = ?")
            params.append(scope)
        if days:
            where.append("datetime(created_at) >= datetime('now', ?)")
            params.append(f"-{days} days")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        query = f"SELECT status, profit_units, play_type FROM plays {clause} AND status != 'PENDING'" if clause else "SELECT status, profit_units, play_type FROM plays WHERE status != 'PENDING'"
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(query, params) as cur:
                rows = await cur.fetchall()
        wins = sum(1 for s, _, _ in rows if s == "WIN")
        losses = sum(1 for s, _, _ in rows if s == "LOSS")
        voids = sum(1 for s, _, _ in rows if s == "VOID")
        cashouts = sum(1 for s, _, _ in rows if s == "CASHOUT")
        units = round(sum(float(p or 0) for _, p, _ in rows), 2)
        total_decisions = wins + losses
        win_rate = round((wins / total_decisions * 100), 1) if total_decisions else 0.0
        breakdown: dict[str, dict[str, int]] = {}
        for status, _, play_type in rows:
            bucket = breakdown.setdefault(play_type, {"WIN": 0, "LOSS": 0, "VOID": 0, "CASHOUT": 0})
            bucket[status] = bucket.get(status, 0) + 1
        return {
            "wins": wins,
            "losses": losses,
            "voids": voids,
            "cashouts": cashouts,
            "units": units,
            "win_rate": win_rate,
            "breakdown": breakdown,
            "graded_count": len(rows),
        }

    async def tail_leaderboard(self, limit: int = 10) -> list[tuple]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                """
                SELECT user_id,
                       SUM(CASE WHEN t.action='TAIL' THEN 1 ELSE 0 END) AS tails,
                       SUM(CASE WHEN t.action='TAIL' AND p.status='WIN' THEN 1 ELSE 0 END) AS tail_wins,
                       SUM(CASE WHEN t.action='TAIL' AND p.status='LOSS' THEN 1 ELSE 0 END) AS tail_losses
                FROM tails t
                JOIN plays p ON p.id = t.play_id
                GROUP BY user_id
                ORDER BY tails DESC, tail_wins DESC
                LIMIT ?
                """,
                (limit,),
            ) as cur:
                return await cur.fetchall()
