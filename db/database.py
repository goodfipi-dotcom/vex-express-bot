import aiosqlite
from datetime import datetime

DB_PATH = "vex.db"


async def init_db():
    """Создание таблиц при старте + миграции"""
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
                charge_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            )
        """)

        # Миграция: добавить charge_id в старую таблицу если её нет
        cursor = await db.execute("PRAGMA table_info(transactions)")
        cols = [row[1] for row in await cursor.fetchall()]
        if "charge_id" not in cols:
            await db.execute("ALTER TABLE transactions ADD COLUMN charge_id TEXT")

        # Уникальный индекс по charge_id (защита от двойных оплат)
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_charge_id "
            "ON transactions(charge_id) WHERE charge_id IS NOT NULL"
        )
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


async def transaction_exists(charge_id: str) -> bool:
    """Проверяет, была ли уже записана оплата с таким charge_id (защита от дублей)"""
    if not charge_id:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM transactions WHERE charge_id = ? LIMIT 1",
            (charge_id,),
        )
        return await cursor.fetchone() is not None


async def add_transaction(
    telegram_id: int,
    plan_id: str,
    plan_name: str,
    amount: int,
    status: str = "paid",
    charge_id: str | None = None,
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO transactions (telegram_id, plan_id, plan_name, amount, status, charge_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (telegram_id, plan_id, plan_name, amount, status, charge_id),
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
