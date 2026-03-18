from pathlib import Path
import aiosqlite


class Database:
    def __init__(self, path: str):
        self.path = Path(path)

    async def init(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)

        async with aiosqlite.connect(self.path.as_posix()) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS plays (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT,
                    channel_id TEXT,
                    user_id TEXT,
                    play_type TEXT,
                    scope TEXT,
                    odds TEXT,
                    units REAL,
                    result TEXT,
                    cashout_units REAL DEFAULT 0,
                    created_at TEXT
                )
            """)
            await db.commit()
