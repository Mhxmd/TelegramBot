"""
db.py – ADVANCED MARKETPLACE DATABASE LAYER (FINAL V3)
Fully synced with:
- bot.py V2
- ui.py unified version
Supports:
- categories
- multi-item orders
- synced ENUMs
- product images
- cart
- checkout
- escrow-ready order flow
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
# CREATE TABLES + ENUMS
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
                    'pending','processing','escrow_hold','shipped','delivered','completed','failed','refunded','disputed'
                ); END IF;

            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname='payment_status')
                THEN CREATE TYPE payment_status AS ENUM ('pending','completed','failed','refunded'); END IF;

            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname='payment_mode')
                THEN CREATE TYPE payment_mode AS ENUM ('paynow','stripe','solana'); END IF;
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

        # ADMIN (optional linking) -----------------------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS admin (
            admin_id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE REFERENCES users(user_id),
            privileges TEXT,
            created_at TIMESTAMP DEFAULT NOW()
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

        # CATEGORY ---------------------------------------------
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

        # CART -------------------------------------------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS cart (
            cart_id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
            product_id INTEGER REFERENCES product(product_id) ON DELETE CASCADE,
            quantity INTEGER DEFAULT 1,
            UNIQUE(user_id, product_id)
        );
        """)

        # ORDERS ----------------------------------------------
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

        # ORDER ITEMS -----------------------------------------
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

        # PAYMENT ---------------------------------------------
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

        print("✅ Tables ready")


# ============================================================
# USER
# ============================================================

async def get_or_create_user(telegram_id: int, username: str):
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT * FROM users WHERE telegram_id=$1", telegram_id
        )
        if user:
            return dict(user)

        new_user = await conn.fetchrow("""
            INSERT INTO users (telegram_id, username)
            VALUES ($1,$2)
            RETURNING *
        """, telegram_id, username)

        return dict(new_user)


async def get_user_by_telegram_id(tg_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", tg_id)
        return dict(row) if row else None


async def get_user_by_id(uid: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", uid)
        return dict(row) if row else None


# ============================================================
# WALLET
# ============================================================

async def get_or_create_wallet(user_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM wallet WHERE user_id=$1", user_id)
        if row:
            return dict(row)

        new_wallet = await conn.fetchrow("""
            INSERT INTO wallet (user_id, solana_address)
            VALUES ($1,$2)
            RETURNING *
        """, user_id, f"sol_{user_id}")

        return dict(new_wallet)


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
        return row["count"] if row else 0


async def get_products_by_category_paginated(category: str, page: int, size: int):
    offset = (page - 1) * size
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.*, c.category_name
            FROM product p
            JOIN category c ON c.category_id=p.category_id
            WHERE c.category_name=$1 AND p.status='active'
            ORDER BY p.product_id DESC
            LIMIT $2 OFFSET $3
        """, category, size, offset)

        # Load images
        result = []
        for r in rows:
            p = dict(r)
            imgs = await conn.fetch(
                "SELECT image_url FROM product_images WHERE product_id=$1 ORDER BY sort_order",
                p["product_id"]
            )
            p["images"] = [i["image_url"] for i in imgs]
            result.append(p)

        return result


# ============================================================
# CART
# ============================================================

async def cart_add_item(user_id: int, pid: int, qty: int):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO cart (user_id,product_id,quantity)
            VALUES ($1,$2,$3)
            ON CONFLICT (user_id,product_id)
            DO UPDATE SET quantity = cart.quantity + EXCLUDED.quantity
        """, user_id, pid, qty)


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


# ============================================================
# CREATE ORDER FROM SINGLE PRODUCT
# ============================================================

async def create_single_product_order(buyer_id: int, product_id: int):
    async with pool.acquire() as conn:
        product = await conn.fetchrow(
            "SELECT * FROM product WHERE product_id=$1",
            product_id
        )
        if not product:
            return None

        seller_id = product["seller_id"]
        price = float(product["price"])

        # decrement stock
        await conn.execute("""
            UPDATE product
            SET stock_quantity = stock_quantity - 1
            WHERE product_id=$1
        """, product_id)

        order = await conn.fetchrow("""
            INSERT INTO orders (buyer_id, seller_id, total_amount, order_status)
            VALUES ($1,$2,$3,'pending')
            RETURNING *
        """, buyer_id, seller_id, price)

        oid = order["order_id"]

        await conn.execute("""
            INSERT INTO order_items (order_id, product_id, quantity, price_each, subtotal)
            VALUES ($1,$2,1,$3,$3)
        """, oid, product_id, price)

        return dict(order)


# ============================================================
# ORDERS
# ============================================================

async def get_order_by_id(order_id: int):
    async with pool.acquire() as conn:
        o = await conn.fetchrow("SELECT * FROM orders WHERE order_id=$1", order_id)
        if not o:
            return None

        o = dict(o)

        items = await conn.fetch("""
            SELECT oi.*, p.title, p.product_id
            FROM order_items oi
            JOIN product p ON p.product_id=oi.product_id
            WHERE oi.order_id=$1
        """, order_id)

        o["items"] = [dict(i) for i in items]
        return o


async def count_orders_by_buyer(buyer_id: int):
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT COUNT(*) FROM orders WHERE buyer_id=$1", buyer_id
        )
        return r["count"]


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
