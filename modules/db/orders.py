# modules/db/orders.py

from . import database   # ✅ FIX: Always import the DATABASE MODULE, not the pool directly


# ------------------------------------------------------------
# CART
# ------------------------------------------------------------

async def cart_add_item(user_id: int, product_id: int, qty: int):
    async with database.pool.acquire() as conn:   # ✅ FIX
        await conn.execute("""
            INSERT INTO cart (user_id, product_id, quantity)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, product_id)
            DO UPDATE SET quantity = cart.quantity + EXCLUDED.quantity
        """, user_id, product_id, qty)


# ------------------------------------------------------------
# ORDER CREATION
# ------------------------------------------------------------

async def create_single_product_order(buyer_id: int, product_id: int):
    async with database.pool.acquire() as conn:   # ✅ FIX
        product = await conn.fetchrow(
            "SELECT * FROM product WHERE product_id=$1",
            product_id
        )
        if not product:
            return None

        seller_id = product["seller_id"]
        price = float(product["price"])

        # Create order
        order = await conn.fetchrow("""
            INSERT INTO orders (buyer_id, seller_id, total_amount, order_status)
            VALUES ($1, $2, $3, 'escrow_hold')
            RETURNING *
        """, buyer_id, seller_id, price)

        oid = order["order_id"]

        # Insert item
        await conn.execute("""
            INSERT INTO order_items (order_id, product_id, quantity, price_each, subtotal)
            VALUES ($1, $2, 1, $3, $3)
        """, oid, product_id, price)

        return dict(order)


async def create_order_from_cart(buyer_id: int):
    async with database.pool.acquire() as conn:   # ✅ FIX
        items = await conn.fetch("""
            SELECT c.product_id, c.quantity, p.price, p.seller_id
            FROM cart c
            JOIN product p ON p.product_id=c.product_id
            WHERE c.user_id=$1
        """, buyer_id)

        if not items:
            return None

        seller_id = items[0]["seller_id"]
        total = sum(float(i["price"]) * i["quantity"] for i in items)

        # Create order
        order = await conn.fetchrow("""
            INSERT INTO orders (buyer_id, seller_id, total_amount)
            VALUES ($1, $2, $3)
            RETURNING *
        """, buyer_id, seller_id, total)

        oid = order["order_id"]

        # Insert items
        for i in items:
            subtotal = float(i["price"]) * i["quantity"]
            await conn.execute("""
                INSERT INTO order_items (order_id, product_id, quantity, price_each, subtotal)
                VALUES ($1, $2, $3, $4, $5)
            """, oid, i["product_id"], i["quantity"], float(i["price"]), subtotal)

        # Clear cart
        await conn.execute("DELETE FROM cart WHERE user_id=$1", buyer_id)

        return dict(order)


# ------------------------------------------------------------
# ORDER READ FUNCTIONS
# ------------------------------------------------------------

async def get_order_by_id(order_id: int):
    async with database.pool.acquire() as conn:   # ✅ FIX
        order = await conn.fetchrow(
            "SELECT * FROM orders WHERE order_id=$1", order_id
        )
        if not order:
            return None

        items = await conn.fetch("""
            SELECT oi.*, p.title
            FROM order_items oi
            JOIN product p ON p.product_id=oi.product_id
            WHERE oi.order_id=$1
        """, order_id)

        data = dict(order)
        data["items"] = [dict(i) for i in items]
        return data


async def count_orders_by_buyer(buyer_id: int):
    async with database.pool.acquire() as conn:   # ✅ FIX
        row = await conn.fetchrow(
            "SELECT COUNT(*) FROM orders WHERE buyer_id=$1",
            buyer_id
        )
        return row["count"]


async def get_orders_by_buyer_paginated(buyer_id: int, page: int, size: int):
    offset = (page - 1) * size
    async with database.pool.acquire() as conn:   # ✅ FIX
        rows = await conn.fetch("""
            SELECT *
            FROM orders
            WHERE buyer_id=$1
            ORDER BY order_id DESC
            LIMIT $2 OFFSET $3
        """, buyer_id, size, offset)

        return [dict(r) for r in rows]
