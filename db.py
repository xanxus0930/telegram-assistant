import aiosqlite
from datetime import datetime
from config import DB_PATH, DEFAULT_PERSONA, DEFAULT_MODELS

CREATE_TABLES = [
    """CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        current_provider TEXT DEFAULT 'gemini',
        persona TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        provider TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS token_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        provider TEXT NOT NULL,
        tokens INTEGER NOT NULL DEFAULT 0,
        date TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        remind_at TEXT NOT NULL,
        is_sent INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS user_models (
        user_id INTEGER NOT NULL,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        PRIMARY KEY (user_id, provider),
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS news_subscriptions (
        user_id INTEGER PRIMARY KEY,
        time_str TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(user_id)
    )""",
]


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        for stmt in CREATE_TABLES:
            await db.execute(stmt)
        await db.commit()


async def get_or_create_user(user_id: int, username: str = "", first_name: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name, persona) VALUES (?, ?, ?, ?)",
            (user_id, username, first_name, DEFAULT_PERSONA),
        )
        await db.commit()


async def get_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def update_user_provider(user_id: int, provider: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET current_provider = ? WHERE user_id = ?", (provider, user_id))
        await db.commit()


async def update_user_persona(user_id: int, persona: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET persona = ? WHERE user_id = ?", (persona, user_id))
        await db.commit()


async def get_conversation(user_id: int, limit: int = 40) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT role, content FROM conversations WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in reversed(rows)]


async def add_message(user_id: int, role: str, content: str, provider: str = ""):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO conversations (user_id, role, content, provider) VALUES (?, ?, ?, ?)",
            (user_id, role, content, provider),
        )
        await db.commit()


async def clear_conversation(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        await db.commit()


async def get_full_conversation_export(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT role, content, provider, created_at FROM conversations WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def add_token_usage(user_id: int, provider: str, tokens: int):
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO token_usage (user_id, provider, tokens, date) VALUES (?, ?, ?, ?)",
            (user_id, provider, tokens, today),
        )
        await db.commit()


async def get_token_usage(user_id: int) -> list[dict]:
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT provider, SUM(tokens) as total FROM token_usage WHERE user_id = ? AND date = ? GROUP BY provider",
            (user_id, today),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def add_reminder(user_id: int, message: str, remind_at: datetime) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO reminders (user_id, message, remind_at) VALUES (?, ?, ?)",
            (user_id, message, remind_at.isoformat()),
        )
        await db.commit()
        return cur.lastrowid


async def get_pending_reminders() -> list[dict]:
    now = datetime.now().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM reminders WHERE remind_at <= ? AND is_sent = 0", (now,)
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def mark_reminder_sent(reminder_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE reminders SET is_sent = 1 WHERE id = ?", (reminder_id,))
        await db.commit()


async def get_user_reminders(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM reminders WHERE user_id = ? AND is_sent = 0 ORDER BY remind_at",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def delete_reminder(reminder_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, user_id))
        await db.commit()


async def get_user_model(user_id: int, provider: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT model FROM user_models WHERE user_id = ? AND provider = ?",
            (user_id, provider),
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else DEFAULT_MODELS.get(provider, "")


async def set_user_model(user_id: int, provider: str, model: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO user_models (user_id, provider, model) VALUES (?, ?, ?)",
            (user_id, provider, model),
        )
        await db.commit()


async def set_news_sub(user_id: int, time_str: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO news_subscriptions (user_id, time_str) VALUES (?, ?)",
            (user_id, time_str),
        )
        await db.commit()


async def get_news_sub(user_id: int) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT time_str FROM news_subscriptions WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
    return row[0] if row else None


async def get_all_news_subs() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id, time_str FROM news_subscriptions") as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def del_news_sub(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM news_subscriptions WHERE user_id = ?", (user_id,))
        await db.commit()
