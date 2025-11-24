# ============================================================
# db.py – FULL MARKETPLACE DATABASE LAYER (FINAL PRODUCTION)
# NO TRIGGERS (T2 MODE)
# Compatible with bot.py V2 and ui.py unified
# Supports:
# - users / wallet / wallet transactions
# - products, categories, media
# - carts
# - orders (multi-item)
# - escrows (hold / release / refund)
# - solana tx logs + on-chain refs
# - stripe + paynow/nets logs
# - buyer↔seller chat system
# - admin controls
# ============================================================

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
                    'pending','processing','escrow_hold','shipped',
                    'delivered','completed','failed','refunded','disputed'
                ); END IF;

            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname='payment_status')
                THEN CREATE TYPE payment_status AS ENUM ('pending','completed','failed','refunded'); END IF;

            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname='payment_mode')
                THEN CREATE TYPE payment_mode AS ENUM (
                    'paynow','nets','stripe','solana'
                ); END IF;
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

        # WALLET ------------------------------------------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS wallet (
            wallet_id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE REFERENCES users(user_id) ON DELETE CASCADE,
            balance DECIMAL(18,2) DEFAULT 0,
            solana_address VARCHAR(200),
            status wallet_status DEFAULT 'active'
        );
        """)

        # WALLET TRANSACTIONS (audit trail)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS wallet_transactions (
            tx_id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(user_id) ON DELETE CASCADE,
            tx_type VARCHAR(20),               -- deposit / withdraw / hold / release / refund / payout
            amount DECIMAL(18,2),
            balance_before DECIMAL(18,2),
            balance_after DECIMAL(18,2),
            ref_order_id INTEGER,
            ref_payment_id INTEGER,
            solana_sig VARCHAR(200),
            details TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # CATEGORIES -------------------------------------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS category (
            category_id SERIAL PRIMARY KEY,
            category_name VARCHAR(120) UNIQUE NOT NULL
        );
        """)

        # Seed categories
        await conn.execute("""
        INSERT INTO category (category_name)
        VALUES
        ('General'),
        ('Electronics'),
        ('Clothing'),
         ('Books'),
        ('Services')
        ON CONFLICT DO NOTHING;""")


        # PRODUCT ----------------------------------------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS product (
            product_id SERIAL PRIMARY KEY,
            seller_id INTEGER REFERENCES users(user_id),
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
            product_id INTEGER REFERENCES product(product_id),
            quantity INTEGER DEFAULT 1,
            UNIQUE(user_id, product_id)
        );
        """)

        # ORDERS -----------------------------------------------
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

        # ORDER ITEMS ------------------------------------------
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

        # PAYMENT -----------------------------------------------
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS payment (
            payment_id SERIAL PRIMARY KEY,
            order_id INTEGER REFERENCES orders(order_id) ON DELETE CASCADE,
            payment_mode payment_mode,
            amount DECIMAL(18,2),
            payment_status payment_status DEFAULT 'pending',
            transaction_hash VARCHAR(200),
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # CHAT (buyer ↔ seller)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            msg_id SERIAL PRIMARY KEY,
            order_id INTEGER REFERENCES orders(order_id),
            sender_id INTEGER REFERENCES users(user_id),
            receiver_id INTEGER REFERENCES users(user_id),
            message_text TEXT,
            message_image TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        print("✅ Tables ready")

# ============================================================
# USER FUNCTIONS
# ============================================================

async def get_or_create_user(telegram_id, username):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", telegram_id)
        if row:
            return dict(row)

        row = await conn.fetchrow("""
            INSERT INTO users (telegram_id, username)
            VALUES ($1,$2)
            RETURNING *
        """, telegram_id, username)
        return dict(row)

async def get_user_by_telegram_id(tg_id):
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM users WHERE telegram_id=$1", tg_id)
        return dict(r) if r else None

async def get_user_by_id(uid):
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM users WHERE user_id=$1", uid)
        return dict(r) if r else None


# ============================================================
# WALLET SYSTEM (NO TRIGGERS — MANUAL SYNC)
# ============================================================

async def get_wallet(user_id: int):
    async with pool.acquire() as conn:
        w = await conn.fetchrow("SELECT * FROM wallet WHERE user_id=$1", user_id)
        return dict(w) if w else None


async def get_or_create_wallet(user_id: int):
    async with pool.acquire() as conn:
        w = await conn.fetchrow("SELECT * FROM wallet WHERE user_id=$1", user_id)
        if w:
            return dict(w)

        w = await conn.fetchrow("""
            INSERT INTO wallet (user_id, solana_address)
            VALUES ($1, $2)
            RETURNING *
        """, user_id, f"sol_{user_id}")

        return dict(w)


# ---- Internal balance update (ONLY place that updates balance) ----
async def _update_wallet_balance(user_id: int, new_balance: float):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE wallet SET balance=$1 WHERE user_id=$2
        """, new_balance, user_id)


# ---- Wallet Transaction Logging ----
async def log_wallet_tx(user_id, tx_type, amount, balance_before, balance_after,
                        ref_order_id=None, ref_payment_id=None, solana_sig=None, details=None):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO wallet_transactions
            (user_id, tx_type, amount, balance_before, balance_after,
             ref_order_id, ref_payment_id, solana_sig, details)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        """,
        user_id, tx_type, amount, balance_before, balance_after,
        ref_order_id, ref_payment_id, solana_sig, details)


# ---- Deposit ----
async def wallet_deposit(user_id: int, amount: float, ref_payment_id=None, details=None):
    wallet = await get_or_create_wallet(user_id)
    before = float(wallet["balance"])
    after = before + amount

    await _update_wallet_balance(user_id, after)
    await log_wallet_tx(user_id, "deposit", amount, before, after,
                        ref_payment_id=ref_payment_id, details=details)
    return after

# ---- Withdraw ----
async def wallet_withdraw(user_id: int, amount: float, details=None):
    wallet = await get_or_create_wallet(user_id)
    before = float(wallet["balance"])

    if before < amount:
        raise Exception("Insufficient balance")

    after = before - amount
    await _update_wallet_balance(user_id, after)
    await log_wallet_tx(user_id, "withdraw", amount, before, after, details=details)
    return after

# ---- Escrow Hold ----
async def wallet_hold(user_id, amount, order_id):
    wallet = await get_or_create_wallet(user_id)
    before = float(wallet["balance"])
    after = before - amount
    if after < 0:
        raise Exception("Insufficient balance")

    await _update_wallet_balance(user_id, after)
    await log_wallet_tx(user_id, "hold", amount, before, after,
                        ref_order_id=order_id, details="Escrow Hold")

# ---- Release Escrow ----
async def wallet_release(user_id, amount, order_id):
    wallet = await get_or_create_wallet(user_id)
    before = float(wallet["balance"])
    after = before + amount

    await _update_wallet_balance(user_id, after)
    await log_wallet_tx(user_id, "release", amount, before, after,
                        ref_order_id=order_id, details="Escrow Released")

# ---- Refund ----
async def wallet_refund(user_id, amount, order_id):
    wallet = await get_or_create_wallet(user_id)
    before = float(wallet["balance"])
    after = before + amount

    await _update_wallet_balance(user_id, after)
    await log_wallet_tx(user_id, "refund", amount, before, after,
                        ref_order_id=order_id, details="Refund")

# ---- Payout Seller ----
async def wallet_payout(user_id, amount, order_id):
    wallet = await get_or_create_wallet(user_id)
    before = float(wallet["balance"])
    after = before + amount

    await _update_wallet_balance(user_id, after)
    await log_wallet_tx(user_id, "payout", amount, before, after,
                        ref_order_id=order_id, details="Seller Payout")


# ============================================================
# CATEGORY
# ============================================================

async def get_all_categories():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM category ORDER BY category_id")
        return [dict(r) for r in rows]


# ============================================================
# PRODUCTS
# ============================================================

async def create_product(seller_id, title, desc, price, qty, category_id):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO product (seller_id,title,description,price,stock_quantity,category_id)
            VALUES ($1,$2,$3,$4,$5,$6)
            RETURNING *
        """, seller_id, title, desc, price, qty, category_id)
        p = dict(row)
        p["images"] = []
        return p

async def add_product_image(product_id, image_url):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO product_images (product_id,image_url,sort_order)
            VALUES (
                $1,$2,
                COALESCE(
                    (SELECT MAX(sort_order)+1 FROM product_images WHERE product_id=$1),
                    0
                )
            )
        """, product_id, image_url)


async def get_product_by_id(pid):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT * FROM product WHERE product_id=$1
        """, pid)

        if not row:
            return None

        imgs = await conn.fetch("""
            SELECT image_url FROM product_images
            WHERE product_id=$1 ORDER BY sort_order
        """, pid)

        p = dict(row)
        p["images"] = [i["image_url"] for i in imgs]
        return p


async def get_seller_products(uid):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.*,
            COALESCE(ARRAY_AGG(pi.image_url) FILTER (WHERE pi.image_url IS NOT NULL), '{}') AS images
            FROM product p
            LEFT JOIN product_images pi ON p.product_id=pi.product_id
            WHERE p.seller_id=$1 AND p.status='active'
            GROUP BY p.product_id
            ORDER BY p.product_id DESC
        """, uid)
        return [dict(r) for r in rows]


async def seller_delete_product(pid):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE product SET status='deleted'
            WHERE product_id=$1
        """, pid)


# ============================================================
# SHOP / CATEGORY PAGINATION
# ============================================================

async def count_products_by_category(cat):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT COUNT(*)
            FROM product p
            JOIN category c ON c.category_id=p.category_id
            WHERE c.category_name=$1 AND p.status='active'
        """, cat)
        return row["count"]

async def get_products_by_category_paginated(cat, page, size):
    offset = (page - 1) * size
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.*, c.category_name
            FROM product p
            JOIN category c ON c.category_id=p.category_id
            WHERE c.category_name=$1 AND p.status='active'
            ORDER BY p.product_id DESC
            LIMIT $2 OFFSET $3
        """, cat, size, offset)

        out = []
        for r in rows:
            pid = r["product_id"]
            imgs = await conn.fetch("""
                SELECT image_url FROM product_images
                WHERE product_id=$1 ORDER BY sort_order
            """, pid)
            p = dict(r)
            p["images"] = [i["image_url"] for i in imgs]
            out.append(p)
        return out


# ============================================================
# CART
# ============================================================

async def cart_add_item(user_id, pid, qty):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO cart (user_id,product_id,quantity)
            VALUES ($1,$2,$3)
            ON CONFLICT (user_id,product_id)
            DO UPDATE SET quantity = cart.quantity + EXCLUDED.quantity
        """, user_id, pid, qty)

async def cart_clear(user_id):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM cart WHERE user_id=$1", user_id)

async def cart_get(user_id):
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
# ORDERS + ESCROW READY
# ============================================================

async def create_single_product_order(buyer_id, product_id):
    async with pool.acquire() as conn:
        p = await conn.fetchrow("SELECT * FROM product WHERE product_id=$1", product_id)
        if not p: return None

        seller = p["seller_id"]
        price = float(p["price"])

        # Reduce stock
        await conn.execute("""
            UPDATE product SET stock_quantity = stock_quantity - 1
            WHERE product_id=$1
        """, product_id)

        # Create order
        row = await conn.fetchrow("""
            INSERT INTO orders (buyer_id,seller_id,total_amount,order_status)
            VALUES ($1,$2,$3,'pending')
            RETURNING *
        """, buyer_id, seller, price)

        oid = row["order_id"]

        # Add item
        await conn.execute("""
            INSERT INTO order_items (order_id,product_id,quantity,price_each,subtotal)
            VALUES ($1,$2,1,$3,$3)
        """, oid, product_id, price)

        return dict(row)


async def get_order_by_id(order_id):
    async with pool.acquire() as conn:
        o = await conn.fetchrow("SELECT * FROM orders WHERE order_id=$1", order_id)
        if not o: return None

        items = await conn.fetch("""
            SELECT oi.*, p.title
            FROM order_items oi
            JOIN product p ON p.product_id=oi.product_id
            WHERE order_id=$1
        """, order_id)

        d = dict(o)
        d["items"] = [dict(i) for i in items]
        return d


async def count_orders_by_buyer(bid):
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT COUNT(*) FROM orders WHERE buyer_id=$1", bid)
        return r["count"]


async def get_orders_by_buyer_paginated(bid, page, size):
    offset = (page - 1) * size
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM orders
            WHERE buyer_id=$1
            ORDER BY order_id DESC
            LIMIT $2 OFFSET $3
        """, bid, size, offset)
        return [dict(r) for r in rows]


# ============================================================
# PAYMENT GATEWAY LOGGING
# ============================================================

async def create_payment(order_id, mode, amount, tx_hash=None):
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO payment (order_id,payment_mode,amount,transaction_hash)
            VALUES ($1,$2,$3,$4)
            RETURNING *
        """, order_id, mode, amount, tx_hash)
        return dict(row)


# ============================================================
# CHAT
# ============================================================

async def chat_send(order_id, sender, receiver, text=None, image=None):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO chat_messages (order_id,sender_id,receiver_id,message_text,message_image)
            VALUES ($1,$2,$3,$4,$5)
        """, order_id, sender, receiver, text, image)


async def chat_get(order_id):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT cm.*, u.username AS sender_name
            FROM chat_messages cm
            JOIN users u ON u.user_id = cm.sender_id
            WHERE order_id=$1
            ORDER BY created_at ASC
        """, order_id)
        return [dict(r) for r in rows]


# ============================================================
# ADMIN
# ============================================================

async def admin_get_stats():
    async with pool.acquire() as conn:
        return {
            "users": await conn.fetchval("SELECT COUNT(*) FROM users"),
            "products": await conn.fetchval("SELECT COUNT(*) FROM product"),
            "orders": await conn.fetchval("SELECT COUNT(*) FROM orders"),
            "payments": await conn.fetchval("SELECT COUNT(*) FROM payment"),
            "wallet_txs": await conn.fetchval("SELECT COUNT(*) FROM wallet_transactions")
        }

async def admin_count_users():
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM users")

async def admin_get_users_paginated(page, size):
    offset = (page - 1) * size
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM users
            ORDER BY user_id ASC
            LIMIT $1 OFFSET $2
        """, size, offset)
        return [dict(r) for r in rows]

async def admin_promote_user(uid):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users SET role =
                CASE 
                    WHEN role='buyer' THEN 'seller'
                    WHEN role='seller' THEN 'admin'
                    ELSE 'admin'
                END
            WHERE user_id=$1
        """, uid)

async def admin_demote_user(uid):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE users SET role =
                CASE 
                    WHEN role='admin' THEN 'seller'
                    WHEN role='seller' THEN 'buyer'
                    ELSE 'buyer'
                END
            WHERE user_id=$1
        """, uid)

async def admin_lock_wallet(uid):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE wallet SET status='locked'
            WHERE user_id=$1
        """, uid)

async def admin_unlock_wallet(uid):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE wallet SET status='active'
            WHERE user_id=$1
        """, uid)

async def admin_count_products():
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM product")

async def admin_get_products_paginated(page, size):
    offset = (page - 1) * size
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM product
            ORDER BY product_id DESC
            LIMIT $1 OFFSET $2
        """, size, offset)
        products = [dict(r) for r in rows]

        for p in products:
            pid = p["product_id"]
            imgs = await conn.fetch("""
                SELECT image_url FROM product_images
                WHERE product_id=$1 ORDER BY sort_order
            """, pid)
            p["images"] = [i["image_url"] for i in imgs]

        return products

async def admin_delete_product(pid):
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE product SET status='deleted'
            WHERE product_id=$1
        """, pid)

# ============================================================
# PUBLIC FEED (ALL PRODUCTS)
# ============================================================

async def count_all_products():
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM product WHERE status='active'")

async def get_all_products_paginated(page: int, size: int):
    offset = (page - 1) * size
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.*, 
                   COALESCE(ARRAY_AGG(pi.image_url) FILTER (WHERE pi.image_url IS NOT NULL), '{}') AS images
            FROM product p
            LEFT JOIN product_images pi ON p.product_id = pi.product_id
            WHERE p.status='active'
            GROUP BY p.product_id
            ORDER BY p.product_id DESC
            LIMIT $1 OFFSET $2
        """, size, offset)

        return [dict(r) for r in rows]
