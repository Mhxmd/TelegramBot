"""
db.py – ADVANCED MARKETPLACE DATABASE LAYER
PostgreSQL (asyncpg) – Multi-Item Orders Enabled
Compatible with bot.py v2 and ui.py v2 (category browsing, product cards, checkout, etc.)
"""

import os
import asyncpg
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")

pool: asyncpg.pool.Pool = None


# ============================================================
# INIT
# ============================================================

async def init_db():
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
        await create_tables()
        print("✅ DB initialised")


# ============================================================
# CREATE TABLES (ALL ERD TABLES)
# ============================================================

async def create_tables():
    async with pool.acquire() as conn:

        # ENUMS ------------------------------------------------
        await conn.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname='user_role')
                THEN CREATE TYPE user_role AS ENUM ('buyer','seller','admin'); END IF;

            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname='product_status')
                THEN CREATE TYPE product_status AS ENUM ('active','inactive','deleted'); END IF;

            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname='wallet_status')
                THEN CREATE TYPE wallet_status AS ENUM ('active','inactive','locked'); END IF;

            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname='order_status')
                THEN CREATE TYPE order_status AS ENUM (
                    'pending','escrow_hold','shipped','released','failed','refunded','disputed'
                ); END IF;

            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname='payment_status')
                THEN CREATE TYPE payment_status AS ENUM ('pending','completed','failed','refunded'); END IF;

            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname='payment_mode')
                THEN CREATE TYPE payment_mode AS ENUM ('paynow','stripe','solana','crypto','other'); END IF;
        END $$;
        """)

        # USERS ------------------------------------------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            username VARCHAR(32),
            role user_role DEFAULT 'buyer',
            verification_status BOOLEAN DEFAULT FALSE,
            date_joined TIMESTAMP DEFAULT NOW()
        );
        """)

        # WALLET -----------------------------------------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS wallet (
            wallet_id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
            balance DECIMAL(18,2) DEFAULT 0,
            solana_address VARCHAR(120),
            status wallet_status DEFAULT 'active'
        );
        """)

        # CATEGORY TABLE ---------------------------------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS category (
            category_id SERIAL PRIMARY KEY,
            category_name VARCHAR(80) UNIQUE NOT NULL
        );
        """)

        # PRODUCT ----------------------------------------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS product (
            product_id SERIAL PRIMARY KEY,
            seller_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
            title VARCHAR(120),
            description TEXT,
            price DECIMAL(18,2),
            stock_quantity INTEGER DEFAULT 0,
            category_id INTEGER REFERENCES category(category_id),
            status product_status DEFAULT 'active',
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # PRODUCT IMAGES ---------------------------------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS product_images (
            image_id SERIAL PRIMARY KEY,
            product_id INTEGER REFERENCES product(product_id) ON DELETE CASCADE,
            image_url TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0
        );
        """)

        # CART --------------------------------------------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS cart (
            cart_id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
            product_id INTEGER REFERENCES product(product_id) ON DELETE CASCADE,
            quantity INTEGER DEFAULT 1,
            UNIQUE(user_id, product_id)
        );
        """)

        # ORDERS (HEADER ONLY) ----------------------------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id SERIAL PRIMARY KEY,
            buyer_id INTEGER REFERENCES users(user_id),
            seller_id INTEGER REFERENCES users(user_id),
            total_amount DECIMAL(18,2),
            order_status order_status DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # ORDER ITEMS (multi-product) ----------------------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            item_id SERIAL PRIMARY KEY,
            order_id INTEGER REFERENCES orders(order_id) ON DELETE CASCADE,
            product_id INTEGER REFERENCES product(product_id),
            quantity INTEGER,
            price_each DECIMAL(18,2),
            subtotal DECIMAL(18,2)
        );
        """)

        # PAYMENTS ----------------------------------------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS payment (
            payment_id SERIAL PRIMARY KEY,
            order_id INTEGER REFERENCES orders(order_id) ON DELETE CASCADE,
            payment_mode payment_mode,
            amount DECIMAL(18,2),
            payment_status payment_status DEFAULT 'pending',
            transaction_hash VARCHAR(120),
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # CHAT --------------------------------------------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS chat (
            chat_id SERIAL PRIMARY KEY,
            buyer_id INTEGER REFERENCES users(user_id),
            seller_id INTEGER REFERENCES users(user_id),
            order_id INTEGER REFERENCES orders(order_id),
            message_content TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # DISPUTES ----------------------------------------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS dispute (
            dispute_id SERIAL PRIMARY KEY,
            order_id INTEGER REFERENCES orders(order_id),
            raised_by INTEGER REFERENCES users(user_id),
            handled_by INTEGER REFERENCES users(user_id),
            reason TEXT,
            decision TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            resolved_at TIMESTAMP
        );
        """)

        print("✅ Tables ready")


# ============================================================
# USER FUNCTIONS
# ============================================================

async def get_or_create_user(telegram_id: int, username: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id=$1", telegram_id
        )
        if row:
            return dict(row)

        new_row = await conn.fetchrow("""
            INSERT INTO users (telegram_id, username)
            VALUES ($1,$2)
            RETURNING *
        """, telegram_id, username)

        return dict(new_row)


async def get_user_by_telegram_id(tg_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id=$1",
            tg_id
        )
        return dict(row) if row else None


async def get_user_by_id(uid: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE user_id=$1",
            uid
        )
        return dict(row) if row else None


# ============================================================
# WALLET
# ============================================================

async def get_or_create_wallet(user_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM wallet WHERE user_id=$1",
            user_id
        )
        if row:
            return dict(row)

        row = await conn.fetchrow("""
            INSERT INTO wallet (user_id, solana_address)
            VALUES ($1,$2)
            RETURNING *
        """, user_id, f"sol_{user_id}")

        return dict(row)


# ============================================================
# CATEGORY
# ============================================================

async def get_all_categories():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM category ORDER BY category_id")
        return [dict(r) for r in rows]


# ============================================================
# PRODUCT + IMAGES
# ============================================================

async def create_product(seller_id: int, title: str, desc: str, price: float, qty: int, category_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO product (seller_id,title,description,price,stock_quantity,category_id)
            VALUES ($1,$2,$3,$4,$5,$6)
            RETURNING *
        """, seller_id, title, desc, price, qty, category_id)
        return dict(row)


async def add_product_image(product_id: int, img: str, order: int = 0):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO product_images (product_id, image_url, sort_order)
            VALUES ($1,$2,$3)
        """, product_id, img, order)


async def get_product_by_id(pid: int):
    async with pool.acquire() as conn:
        p = await conn.fetchrow("SELECT * FROM product WHERE product_id=$1", pid)
        if not p:
            return None
        images = await conn.fetch(
            "SELECT image_url FROM product_images WHERE product_id=$1 ORDER BY sort_order",
            pid
        )
        d = dict(p)
        d["images"] = [i["image_url"] for i in images]
        return d


# ============================================================
# PAGINATED BROWSING
# ============================================================

async def count_products_by_category(category: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT COUNT(*) FROM product p
            JOIN category c ON c.category_id=p.category_id
            WHERE c.category_name=$1 AND p.status='active'
        """, category)
        return row["count"]


async def get_products_by_category_paginated(category: str, page: int, page_size: int):
    offset = (page - 1) * page_size
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.*, c.category_name
            FROM product p
            JOIN category c ON c.category_id=p.category_id
            WHERE c.category_name=$1 AND p.status='active'
            ORDER BY p.product_id DESC
            LIMIT $2 OFFSET $3
        """, category, page_size, offset)
        return [dict(r) for r in rows]


# ============================================================
# CART
# ============================================================

async def cart_add_item(user_id: int, product_id: int, qty: int):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO cart (user_id,product_id,quantity)
            VALUES ($1,$2,$3)
            ON CONFLICT (user_id,product_id)
            DO UPDATE SET quantity = cart.quantity + EXCLUDED.quantity
        """, user_id, product_id, qty)


async def cart_get(user_id: int):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.product_id, c.quantity,
                   p.title, p.price, p.seller_id
            FROM cart c
            JOIN product p ON p.product_id=c.product_id
            WHERE c.user_id=$1
        """, user_id)
        return [dict(r) for r in rows]


async def cart_clear(user_id: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM cart WHERE user_id=$1", user_id)


# ============================================================
# CREATE FULL ORDER (HEADER + ITEMS)
# ============================================================

async def create_order_from_cart(buyer_id: int):
    """
    Creates:
    - order
    - order_items[]
    - clears the cart
    - auto-detects seller_id from FIRST product (assuming single seller per checkout)
    """
    items = await cart_get(buyer_id)
    if not items:
        return None

    seller_id = items[0]["seller_id"]   # assumes single seller marketplace
    total = sum(float(i["price"]) * i["quantity"] for i in items)

    async with pool.acquire() as conn:
        order_row = await conn.fetchrow("""
            INSERT INTO orders (buyer_id, seller_id, total_amount)
            VALUES ($1,$2,$3)
            RETURNING *
        """, buyer_id, seller_id, total)

        order_id = order_row["order_id"]

        for it in items:
            price = float(it["price"])
            qty = int(it["quantity"])
            subtotal = price * qty

            await conn.execute("""
                INSERT INTO order_items (order_id,product_id,quantity,price_each,subtotal)
                VALUES ($1,$2,$3,$4,$5)
            """, order_id, it["product_id"], qty, price, subtotal)

        await conn.execute("DELETE FROM cart WHERE user_id=$1", buyer_id)

        return dict(order_row)


# ============================================================
# ORDERS + ORDER ITEMS
# ============================================================

async def get_order_by_id(order_id: int):
    async with pool.acquire() as conn:
        order = await conn.fetchrow("SELECT * FROM orders WHERE order_id=$1", order_id)
        if not order:
            return None
        order = dict(order)

        items = await conn.fetch("""
            SELECT oi.*, p.title, p.product_id
            FROM order_items oi
            JOIN product p ON p.product_id=oi.product_id
            WHERE oi.order_id=$1
        """, order_id)

        order["items"] = [dict(i) for i in items]
        return order


async def count_orders_by_buyer(buyer_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) FROM orders WHERE buyer_id=$1",
            buyer_id
        )
        return row["count"]


async def get_orders_by_buyer_paginated(buyer_id: int, page: int, size: int):
    offset = (page - 1) * size
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM orders
            WHERE buyer_id=$1
            ORDER BY order_id DESC
            LIMIT $2 OFFSET $3
        """, buyer_id, size, offset)
        return [dict(r) for r in rows]


# ============================================================
# PAYMENT
# ============================================================

async def create_payment(order_id: int, mode: str, amount: float, tx_hash=None):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO payment (order_id,payment_mode,amount,transaction_hash)
            VALUES ($1,$2,$3,$4)
        """, order_id, mode, amount, tx_hash)
