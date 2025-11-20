# modules/db/users.py

from . import database   # <-- fix

async def get_or_create_user(tg_id: int, username: str):
    async with database.pool.acquire() as conn:   # <-- fix
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id=$1", tg_id
        )
        if row:
            return dict(row)

        new_row = await conn.fetchrow("""
            INSERT INTO users (telegram_id, username)
            VALUES ($1, $2)
            RETURNING *
        """, tg_id, username)

        return dict(new_row)


async def get_user_by_telegram_id(tg_id: int):
    async with database.pool.acquire() as conn:   # <-- fix
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id=$1",
            tg_id
        )
        return dict(row) if row else None


async def get_user_by_id(uid: int):
    async with database.pool.acquire() as conn:   # <-- fix
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE user_id=$1",
            uid
        )
        return dict(row) if row else None
