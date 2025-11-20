import os
import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL")
pool: asyncpg.pool.Pool = None

async def init_db():
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
        await create_tables()
        print("✅ DB initialised")

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

        # DISPUTES ---------------------------------------------
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
