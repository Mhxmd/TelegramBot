# modules/db/payments.py

from . import database   # ✅ FIX: import the live database module, NOT the pool directly


async def create_payment(order_id, mode, amount, tx_hash=None):
    """
    Create a new payment record for an order.
    """
    async with database.pool.acquire() as conn:   # ✅ FIX: use database.pool
        await conn.execute("""
            INSERT INTO payment (order_id, payment_mode, amount, transaction_hash)
            VALUES ($1, $2, $3, $4)
        """, order_id, mode, amount, tx_hash)
