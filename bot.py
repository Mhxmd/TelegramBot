# ============================================================
# TELEGRAM MARKETPLACE BOT – V2 (SQL ONLY)
# Clean version: DB init BEFORE polling, modular DB + modular UI
# ============================================================

import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ------------------------------------------------------------
# Environment
# ------------------------------------------------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")

# ------------------------------------------------------------
# Modules
# ------------------------------------------------------------
from modules import db        # all DB functions (users, wallet, orders, etc.)
from modules import ui        # UI builders (menus, cards, etc.)

# ------------------------------------------------------------
# Logging
# ------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("marketbot_v2")


# ============================================================
# Helpers
# ============================================================

def _uid(update: Update) -> int:
    return update.effective_user.id


async def safe_edit(q, text, kb=None):
    try:
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await q.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")


# ============================================================
# /start
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = _uid(update)
    username = update.effective_user.username or f"user_{uid}"

    # Create user & wallet
    user_row = await db.get_or_create_user(uid, username)
    await db.get_or_create_wallet(user_row["user_id"])

    # Build UI
    text, kb = await ui.build_main_menu(user_row["user_id"])
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")


# ============================================================
# UI ROUTES
# ============================================================

async def handle_main(update, context, q):
    uid = _uid(update)
    user_row = await db.get_user_by_telegram_id(uid)
    text, kb = await ui.build_main_menu(user_row["user_id"])
    await safe_edit(q, text, kb)


async def handle_categories(update, context, q):
    cats = await db.get_all_categories()
    if not cats:
        return await safe_edit(q, "❌ No categories available.")

    text, kb = ui.build_category_menu([c["category_name"] for c in cats])
    await safe_edit(q, text, kb)


async def handle_category_page(update, context, q, category, page):
    uid = _uid(update)
    total = await db.count_products_by_category(category)

    if total == 0:
        return await safe_edit(q, f"❌ No products in `{category}`")

    size = 1
    total_pages = max((total + size - 1) // size, 1)

    # wrap-around pagination
    if page < 1:
        page = total_pages
    if page > total_pages:
        page = 1

    products = await db.get_products_by_category_paginated(category, page, size)
    product = products[0]

    card = ui.build_product_photo_card(product, page, total_pages)

    await context.bot.send_photo(
        chat_id=uid,
        photo=card["photo_url"],
        caption=card["caption"],
        reply_markup=card["reply_markup"],
        parse_mode="Markdown",
    )


async def handle_product(update, context, q, pid):
    uid = _uid(update)
    product = await db.get_product_by_id(pid)

    if not product:
        return await safe_edit(q, "❌ Product not found.")

    card = ui.build_product_photo_card(product, 1, 1)

    await context.bot.send_photo(
        chat_id=uid,
        photo=card["photo_url"],
        caption=card["caption"],
        reply_markup=card["reply_markup"],
        parse_mode="Markdown",
    )


async def handle_cart_add(update, context, q, pid, qty):
    uid = _uid(update)
    user_row = await db.get_user_by_telegram_id(uid)
    await db.cart_add_item(user_row["user_id"], pid, qty)
    await q.answer("🛒 Added to cart")


async def handle_orders(update, context, q, page=1):
    uid = _uid(update)
    user = await db.get_user_by_telegram_id(uid)

    total = await db.count_orders_by_buyer(user["user_id"])
    size = 5
    total_pages = max((total + size - 1) // size, 1)

    orders = await db.get_orders_by_buyer_paginated(user["user_id"], page, size)
    text, kb = ui.build_orders_list(orders, "buyer", page, total_pages)

    await safe_edit(q, text, kb)


async def handle_order_view(update, context, q, oid, role):
    order = await db.get_order_by_id(oid)
    if not order:
        return await safe_edit(q, "❌ Order not found.")

    product = await db.get_product_by_id(order["items"][0]["product_id"])
    buyer = await db.get_user_by_id(order["buyer_id"])
    seller = await db.get_user_by_id(order["seller_id"])

    text, kb = ui.build_order_summary(order, product, buyer, seller, role)
    await safe_edit(q, text, kb)


async def handle_wallet(update, context, q):
    uid = _uid(update)
    user = await db.get_user_by_telegram_id(uid)
    wallet = await db.get_or_create_wallet(user["user_id"])

    text, kb = ui.build_wallet_dashboard(wallet, user)
    await safe_edit(q, text, kb)


async def handle_admin(update, context, q):
    uid = _uid(update)
    if uid != ADMIN_ID:
        return await q.answer("🚫 Admin only", show_alert=True)

    text, kb = ui.build_admin_panel_menu()
    await safe_edit(q, text, kb)


async def start_checkout(update, context, q, pid):
    uid = _uid(update)
    user = await db.get_user_by_telegram_id(uid)

    order = await db.create_single_product_order(user["user_id"], pid)
    text, kb = ui.build_payment_method_menu(order["order_id"], order["total_amount"])

    await safe_edit(q, text, kb)


# ============================================================
# CALLBACK ROUTER
# ============================================================

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data

    try:
        await q.answer()
    except Exception:
        pass

    # MAIN
    if data == "v2:menu:main":
        return await handle_main(update, context, q)

    # CATEGORIES
    if data == "v2:shop:categories":
        return await handle_categories(update, context, q)

    if data.startswith("v2:shop:cat:"):
        _, _, _, category = data.split(":", 3)
        return await handle_category_page(update, context, q, category, 1)

    # CATEGORY PAGINATION
    if data.startswith("v2:shop:page:"):
        _, _, _, category, page = data.split(":", 4)
        return await handle_category_page(update, context, q, category, int(page))

    # PRODUCT VIEW
    if data.startswith("v2:shop:product:"):
        _, _, _, pid = data.split(":", 3)
        return await handle_product(update, context, q, int(pid))

    # CART
    if data.startswith("v2:cart:add:"):
        _, _, _, pid, qty = data.split(":", 4)
        return await handle_cart_add(update, context, q, int(pid), int(qty))

    # ORDERS
    if data == "v2:buyer:orders":
        return await handle_orders(update, context, q, 1)

    if data.startswith("v2:buyer:orders_page:"):
        _, _, _, page = data.split(":", 3)
        return await handle_orders(update, context, q, int(page))

    # ORDER VIEW
    if data.startswith("v2:order:view:"):
        _, _, _, oid, role = data.split(":", 4)
        return await handle_order_view(update, context, q, int(oid), role)

    # WALLET
    if data in ("v2:wallet:dashboard", "v2:wallet:refresh"):
        return await handle_wallet(update, context, q)

    # CHECKOUT
    if data.startswith("v2:checkout:"):
        _, _, pid = data.split(":")
        return await start_checkout(update, context, q, int(pid))

    # ADMIN
    if data == "v2:admin:panel":
        return await handle_admin(update, context, q)

    logger.info(f"Unhandled callback: {data}")


# ============================================================
# MESSAGE HANDLER
# ============================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use /start to open the marketplace.")


# ============================================================
# MAIN (WINDOWS SAFE VERSION)
# ============================================================

def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN missing in .env")
        return

    async def setup():
        # Init DB BEFORE polling
        await db.init_db()
        logger.info("Database initialised.")

        app = (
            ApplicationBuilder()
            .token(BOT_TOKEN)
            .build()
        )

        # Handlers
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(callback_router))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        print("🤖 Marketplace Bot — Running")
        return app

    # Create loop manually (Windows-safe)
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = loop.run_until_complete(setup())
    app.run_polling()   # NO await, runs in same thread safely


if __name__ == "__main__":
    main()
