"""
db.py – FULL SQL Marketplace Database Layer
Async PostgreSQL using asyncpg
Aligned 100% with final schema
No JSON anywhere.
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
# CREATE TABLES
# ============================================================
async def create_tables():
    async with pool.acquire() as conn:

        # ENUMS
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
            THEN CREATE TYPE order_status AS ENUM ('pending','escrow_hold','shipped','released','failed','refunded','disputed'); END IF;

            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname='payment_status')
            THEN CREATE TYPE payment_status AS ENUM ('pending','completed','failed','refunded'); END IF;

            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname='payment_mode')
            THEN CREATE TYPE payment_mode AS ENUM ('paynow','stripe','solana','crypto','other'); END IF;
        END $$;
        """)

        # USERS
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

        # WALLET
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS wallet (
            wallet_id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
            balance DECIMAL(18,2) DEFAULT 0,
            solana_address VARCHAR(120),
            status wallet_status DEFAULT 'active'
        );
        """)

        # PRODUCT
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS product (
            product_id SERIAL PRIMARY KEY,
            seller_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
            title VARCHAR(120),
            description TEXT,
            price DECIMAL(18,2),
            stock_quantity INTEGER DEFAULT 0,
            category VARCHAR(64),
            status product_status DEFAULT 'active',
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # PRODUCT IMAGES
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS product_images (
            image_id SERIAL PRIMARY KEY,
            product_id INTEGER REFERENCES product(product_id) ON DELETE CASCADE,
            image_url TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0
        );
        """)

        # CART
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS cart (
            cart_id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
            product_id INTEGER REFERENCES product(product_id) ON DELETE CASCADE,
            quantity INTEGER DEFAULT 1,
            UNIQUE(user_id, product_id)
        );
        """)

        # ORDERS
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id SERIAL PRIMARY KEY,
            buyer_id INTEGER REFERENCES users(user_id),
            seller_id INTEGER REFERENCES users(user_id),
            product_id INTEGER REFERENCES product(product_id),
            quantity INTEGER,
            amount DECIMAL(18,2),
            order_status order_status DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # PAYMENT
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

        # CHAT
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

        # DISPUTE
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

        # ADMIN
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS admin (
            admin_id SERIAL PRIMARY KEY,
            privileges TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        print("✅ Tables ready")


# ============================================================
# USERS
# ============================================================
async def get_or_create_user(telegram_id: int, username: str):
    async with pool.acquire() as conn:
        user = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)
        if user:
            return dict(user)

        new_user = await conn.fetchrow("""
            INSERT INTO users (telegram_id, username)
            VALUES ($1, $2)
            RETURNING *""",
            telegram_id, username)
        return dict(new_user)


async def get_user(user_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", user_id)
        return dict(row) if row else None


# ============================================================
# WALLET
# ============================================================
async def get_or_create_wallet(user_id: int):
    async with pool.acquire() as conn:
        wallet = await conn.fetchrow("SELECT * FROM wallet WHERE user_id=$1", user_id)
        if wallet:
            return dict(wallet)

        new_wallet = await conn.fetchrow("""
            INSERT INTO wallet(user_id, solana_address)
            VALUES ($1, $2)
            RETURNING *;
        """, user_id, f"sol_{user_id}")

        return dict(new_wallet)


async def update_wallet_balance(user_id: int, amount: float):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE wallet SET balance = balance + $1
            WHERE user_id=$2
        """, amount, user_id)


# ============================================================
# PRODUCTS
# ============================================================
async def create_product(seller_id: int, title: str, description: str, price: float, qty: int, category: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO product(seller_id, title, description, price, stock_quantity, category)
            VALUES ($1,$2,$3,$4,$5,$6)
            RETURNING *
        """, seller_id, title, description, price, qty, category)
        return dict(row)


async def add_product_image(product_id: int, url: str, sort_order: int = 0):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO product_images(product_id, image_url, sort_order)
            VALUES ($1,$2,$3)
        """, product_id, url, sort_order)


async def get_product(product_id: int):
    async with pool.acquire() as conn:
        prod = await conn.fetchrow("SELECT * FROM product WHERE product_id=$1", product_id)
        if not prod:
            return None
        imgs = await conn.fetch("SELECT * FROM product_images WHERE product_id=$1 ORDER BY sort_order", product_id)
        return dict(prod), [dict(i) for i in imgs]


async def list_products():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM product WHERE status='active' ORDER BY product_id DESC")
        return [dict(r) for r in rows]


# ============================================================
# CART
# ============================================================
async def cart_add(user_id: int, product_id: int, qty: int):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO cart (user_id, product_id, quantity)
            VALUES ($1,$2,$3)
            ON CONFLICT (user_id, product_id)
            DO UPDATE SET quantity = cart.quantity + EXCLUDED.quantity
        """, user_id, product_id, qty)


async def cart_get(user_id: int):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.cart_id, c.product_id, c.quantity, p.title, p.price
            FROM cart c
            JOIN product p ON c.product_id=p.product_id
            WHERE c.user_id=$1
        """, user_id)
        return [dict(r) for r in rows]


async def cart_remove(user_id: int, product_id: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM cart WHERE user_id=$1 AND product_id=$2", user_id, product_id)


async def cart_clear(user_id: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM cart WHERE user_id=$1", user_id)


# ============================================================
# ORDERS
# ============================================================
async def create_order(buyer_id: int, seller_id: int, product_id: int, qty: int, amount: float):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO orders(buyer_id, seller_id, product_id, quantity, amount)
            VALUES ($1,$2,$3,$4,$5)
            RETURNING *
        """, buyer_id, seller_id, product_id, qty, amount)
        return dict(row)


async def get_order(order_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM orders WHERE order_id=$1", order_id)
        return dict(row) if row else None


async def update_order_status(order_id: int, status: str):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE orders SET order_status=$1 WHERE order_id=$2
        """, status, order_id)


# ============================================================
# PAYMENT
# ============================================================
async def create_payment(order_id: int, mode: str, amount: float, tx: str = None):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO payment(order_id,payment_mode,amount,transaction_hash)
            VALUES ($1,$2,$3,$4)
        """, order_id, mode, amount, tx)


# ============================================================
# CHAT / DISPUTE — simple helpers
# ============================================================
async def create_message(buyer_id, seller_id, order_id, content):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO chat(buyer_id,seller_id,order_id,message_content)
            VALUES ($1,$2,$3,$4)
        """, buyer_id, seller_id, order_id, content)


async def create_dispute(order_id, raised_by, reason):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO dispute(order_id,raised_by,reason)
            VALUES ($1,$2,$3)
        """, order_id, raised_by, reason)


print("db.py loaded")
