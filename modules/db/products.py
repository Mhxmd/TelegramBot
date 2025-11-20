# modules/db/products.py

from . import database   # ✅ FIX: use live module reference (NOT pool copy)

async def create_product(seller_id, title, desc, price, qty, category_id):
    async with database.pool.acquire() as conn:   # ✅ FIX
        row = await conn.fetchrow("""
            INSERT INTO product (seller_id, title, description, price, stock_quantity, category_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
        """, seller_id, title, desc, price, qty, category_id)
        return dict(row)


async def add_product_image(product_id, img, order=0):
    async with database.pool.acquire() as conn:   # ✅ FIX
        await conn.execute("""
            INSERT INTO product_images (product_id, image_url, sort_order)
            VALUES ($1, $2, $3)
        """, product_id, img, order)


async def get_product_by_id(pid: int):
    async with database.pool.acquire() as conn:   # ✅ FIX
        p = await conn.fetchrow(
            "SELECT * FROM product WHERE product_id=$1",
            pid
        )
        if not p:
            return None

        images = await conn.fetch("""
            SELECT image_url
            FROM product_images
            WHERE product_id=$1
            ORDER BY sort_order
        """, pid)

        d = dict(p)
        d["images"] = [i["image_url"] for i in images]
        return d


async def count_products_by_category(category: str):
    async with database.pool.acquire() as conn:   # ✅ FIX
        row = await conn.fetchrow("""
            SELECT COUNT(*) FROM product p
            JOIN category c ON c.category_id = p.category_id
            WHERE c.category_name=$1
              AND p.status='active'
        """, category)
        return row["count"]


async def get_products_by_category_paginated(category, page, size):
    offset = (page - 1) * size

    async with database.pool.acquire() as conn:   # ✅ FIX
        rows = await conn.fetch("""
            SELECT p.*, c.category_name
            FROM product p
            JOIN category c ON c.category_id = p.category_id
            WHERE c.category_name=$1
              AND p.status='active'
            ORDER BY p.product_id DESC
            LIMIT $2 OFFSET $3
        """, category, size, offset)

        return [dict(r) for r in rows]
