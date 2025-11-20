# modules/db/wallet.py

from . import database   # ✅ FIXED — always import the module, not the pool directly


async def get_or_create_wallet(user_id: int):
    async with database.pool.acquire() as conn:   # ✅ FIXED — use database.pool
        row = await conn.fetchrow(
            "SELECT * FROM wallet WHERE user_id=$1",
            user_id
        )

        if row:
            return dict(row)

        new_row = await conn.fetchrow("""
            INSERT INTO wallet (user_id, solana_address)
            VALUES ($1, $2)
            RETURNING *
        """, user_id, f"sol_{user_id}")

        return dict(new_row)
