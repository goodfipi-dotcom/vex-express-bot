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
                referrer_id INTEGER,
                bonus_days_total INTEGER DEFAULT 0,
                notified_expiry INTEGER DEFAULT 0,
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

        # Миграции старых БД
        cursor = await db.execute("PRAGMA table_info(users)")
        user_cols = [row[1] for row in await cursor.fetchall()]
        if "referrer_id" not in user_cols:
            await db.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER")
        if "bonus_days_total" not in user_cols:
            await db.execute("ALTER TABLE users ADD COLUMN bonus_days_total INTEGER DEFAULT 0")
        if "notified_expiry" not in user_cols:
            await db.execute("ALTER TABLE users ADD COLUMN notified_expiry INTEGER DEFAULT 0")

        cursor = await db.execute("PRAGMA table_info(transactions)")
        cols = [row[1] for row in await cursor.fetchall()]
        if "charge_id" not in cols:
            await db.execute("ALTER TABLE transactions ADD COLUMN charge_id TEXT")

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


async def create_or_update_user(telegram_id: int, username: str, first_name: str, referrer_id: int | None = None):
    """Создать или обновить пользователя. referrer_id применяется только при первом создании."""
    async with aiosqlite.connect(DB_PATH) as db:
        existing = await db.execute("SELECT telegram_id FROM users WHERE telegram_id = ?", (telegram_id,))
        row = await existing.fetchone()

        if row:
            await db.execute(
                """UPDATE users SET username = ?, first_name = ? WHERE telegram_id = ?""",
                (username, first_name, telegram_id),
            )
        else:
            # Реферал не может сам себя пригласить
            ref = referrer_id if referrer_id and referrer_id != telegram_id else None
            await db.execute(
                """INSERT INTO users (telegram_id, username, first_name, referrer_id)
                   VALUES (?, ?, ?, ?)""",
                (telegram_id, username, first_name, ref),
            )
        await db.commit()


async def update_subscription(telegram_id: int, vless_key: str, marzban_username: str, end_date: datetime):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE users SET vless_key = ?, marzban_username = ?, subscription_end = ?,
                                notified_expiry = 0
               WHERE telegram_id = ?""",
            (vless_key, marzban_username, end_date.isoformat(), telegram_id),
        )
        await db.commit()


async def grant_referral_bonus(user_id: int, days: int = 7) -> int | None:
    """Начислить +N дней подписки рефереру. Возвращает referrer_id или None."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT referrer_id FROM users WHERE telegram_id = ?", (user_id,))
        row = await cur.fetchone()
        if not row or not row["referrer_id"]:
            return None
        referrer_id = row["referrer_id"]

        # Продлить подписку реферера на days дней
        cur = await db.execute(
            "SELECT subscription_end FROM users WHERE telegram_id = ?",
            (referrer_id,),
        )
        ref_row = await cur.fetchone()
        if not ref_row:
            return None

        now = datetime.now()
        current_end = None
        if ref_row["subscription_end"]:
            try:
                current_end = datetime.fromisoformat(ref_row["subscription_end"])
            except Exception:
                current_end = None

        base = current_end if current_end and current_end > now else now
        from datetime import timedelta
        new_end = base + timedelta(days=days)

        await db.execute(
            """UPDATE users
               SET subscription_end = ?,
                   bonus_days_total = COALESCE(bonus_days_total, 0) + ?
               WHERE telegram_id = ?""",
            (new_end.isoformat(), days, referrer_id),
        )
        await db.commit()
        return referrer_id


async def transaction_exists(charge_id: str) -> bool:
    if not charge_id:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM transactions WHERE charge_id = ? LIMIT 1",
            (charge_id,),
        )
        return await cursor.fetchone() is not None


async def user_payment_count(telegram_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM transactions WHERE telegram_id = ? AND status = 'paid'",
            (telegram_id,),
        )
        row = await cur.fetchone()
        return row[0] if row else 0


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


async def get_users_for_expiry_notify(days_left: int):
    """Вернуть пользователей у которых подписка истечёт через `days_left` дней
    и ещё не отправляли уведомление для этого порога."""
    from datetime import timedelta
    now = datetime.now()
    lo = (now + timedelta(days=days_left)).replace(hour=0, minute=0, second=0, microsecond=0)
    hi = lo + timedelta(days=1)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """SELECT telegram_id, subscription_end, notified_expiry
               FROM users
               WHERE subscription_end >= ? AND subscription_end < ?""",
            (lo.isoformat(), hi.isoformat()),
        )
        return await cur.fetchall()


async def mark_notified_expiry(telegram_id: int, threshold: int):
    """Отметить какое уведомление уже отправлено.
    threshold: 3 — за 3 дня, 1 — за 1 день, 0 — в день истечения."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Битовая маска: 1=3 дней, 2=1 день, 4=в день истечения
        flag = {3: 1, 1: 2, 0: 4}.get(threshold, 0)
        await db.execute(
            "UPDATE users SET notified_expiry = COALESCE(notified_expiry, 0) | ? WHERE telegram_id = ?",
            (flag, telegram_id),
        )
        await db.commit()
