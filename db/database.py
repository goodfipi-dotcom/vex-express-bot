import aiosqlite
from datetime import datetime

DB_PATH = "vex.db"


async def init_db():
    """Создание таблиц при старте"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                vless_key TEXT,
                marzban_username TEXT,
                subscription_end TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                plan_id TEXT,
                plan_name TEXT,
                amount INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            )
        """)
        await db.commit()


async def get_user(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        return await cursor.fetchone()


async def create_or_update_user(telegram_id: int, username: str, first_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO users (telegram_id, username, first_name)
               VALUES (?, ?, ?)
               ON CONFLICT(telegram_id) DO UPDATE SET
               username = excluded.username,
               first_name = excluded.first_name""",
            (telegram_id, username, first_name),
        )
        await db.commit()


async def update_subscription(telegram_id: int, vless_key: str, marzban_username: str, end_date: datetime):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE users SET vless_key = ?, marzban_username = ?, subscription_end = ?
               WHERE telegram_id = ?""",
            (vless_key, marzban_username, end_date.isoformat(), telegram_id),
        )
        await db.commit()


async def add_transaction(telegram_id: int, plan_id: str, plan_name: str, amount: int, status: str = "paid"):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO transactions (telegram_id, plan_id, plan_name, amount, status)
               VALUES (?, ?, ?, ?, ?)""",
            (telegram_id, plan_id, plan_name, amount, status),
        )
        await db.commit()


async def get_transactions(telegram_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM transactions WHERE telegram_id = ? ORDER BY created_at DESC LIMIT 20",
            (telegram_id,),
        )
        return await cursor.fetchall()
