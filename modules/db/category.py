# modules/db/category.py

from . import database   # ✅ FIXED — import the database module, NOT the pool directly


async def get_all_categories():
    async with database.pool.acquire() as conn:   # ✅ FIXED — access pool via module
        rows = await conn.fetch(
            "SELECT * FROM category ORDER BY category_id"
        )
        return [dict(r) for r in rows]
