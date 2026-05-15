import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "labelbot.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                balance REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                crypto_type TEXT NOT NULL,
                tx_hash TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS labels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                username TEXT,
                file_id TEXT NOT NULL,
                charge REAL DEFAULT 18.0,
                status TEXT DEFAULT 'pending',
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            )
        """)
        await db.commit()


async def get_or_create_user(telegram_id: int, username: str, first_name: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "INSERT OR IGNORE INTO users (telegram_id, username, first_name) VALUES (?, ?, ?)",
            (telegram_id, username, first_name),
        )
        await db.commit()
        async with db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row)


async def get_user(telegram_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_balance(telegram_id: int) -> float:
    user = await get_user(telegram_id)
    return user["balance"] if user else 0.0


async def update_balance(telegram_id: int, delta: float) -> float:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET balance = balance + ? WHERE telegram_id = ?",
            (delta, telegram_id),
        )
        await db.commit()
        async with db.execute(
            "SELECT balance FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0.0


async def create_deposit(telegram_id: int, amount: float, crypto_type: str, tx_hash: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO deposits (telegram_id, amount, crypto_type, tx_hash) VALUES (?, ?, ?, ?)",
            (telegram_id, amount, crypto_type, tx_hash),
        )
        await db.commit()
        return cursor.lastrowid


async def get_pending_deposits() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT d.*, u.username, u.first_name
               FROM deposits d JOIN users u ON d.telegram_id = u.telegram_id
               WHERE d.status = 'pending'
               ORDER BY d.created_at DESC"""
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_all_deposits() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT d.*, u.username, u.first_name
               FROM deposits d JOIN users u ON d.telegram_id = u.telegram_id
               ORDER BY d.created_at DESC LIMIT 50"""
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def approve_deposit(deposit_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM deposits WHERE id = ? AND status = 'pending'", (deposit_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            deposit = dict(row)

        await db.execute(
            "UPDATE deposits SET status = 'approved' WHERE id = ?", (deposit_id,)
        )
        await db.execute(
            "UPDATE users SET balance = balance + ? WHERE telegram_id = ?",
            (deposit["amount"], deposit["telegram_id"]),
        )
        await db.commit()
        return deposit


async def reject_deposit(deposit_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM deposits WHERE id = ? AND status = 'pending'", (deposit_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            deposit = dict(row)

        await db.execute(
            "UPDATE deposits SET status = 'rejected' WHERE id = ?", (deposit_id,)
        )
        await db.commit()
        return deposit


async def create_label(telegram_id: int, username: str, file_id: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO labels (telegram_id, username, file_id) VALUES (?, ?, ?)",
            (telegram_id, username, file_id),
        )
        await db.commit()
        return cursor.lastrowid


async def get_all_labels() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT l.*, u.first_name
               FROM labels l JOIN users u ON l.telegram_id = u.telegram_id
               ORDER BY l.submitted_at DESC LIMIT 50"""
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]


async def get_all_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
