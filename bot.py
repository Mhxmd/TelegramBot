# ============================================================
# TELEGRAM MARKETPLACE BOT – V2 (SQL ONLY) — FIXED VERSION
# Fully synced with new ui.py (single-file UI)
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
from modules import db
from modules import ui

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
    """Edits message safely, fallback to send new msg."""
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

    # Ensure user + wallet exist
    user_row = await db.get_or_create_user(uid, username)
    await db.get_or_create_wallet(user_row["user_id"])

    # Show main menu
    text, kb = await ui.build_main_menu(user_row["user_id"])
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")


# ============================================================
# MAIN MENU
# ============================================================

async def handle_main(update, context, q):
    uid = _uid(update)
    user_row = await db.get_user_by_telegram_id(uid)
    text, kb = await ui.build_main_menu(user_row["user_id"])
    await safe_edit(q, text, kb)


# ============================================================
# CATEGORY MENU
# ============================================================

async def handle_categories(update, context, q):
    cats = await db.get_all_categories()
    if not cats:
        return await safe_edit(q, "❌ No categories available.")

    text, kb = ui.build_category_menu(cats)
    await safe_edit(q, text, kb)


async def handle_category_page(update, context, q, category_name, page):
    uid = _uid(update)

    # Count total products
    total_products = await db.count_products_by_category(category_name)
    if total_products == 0:
        return await safe_edit(q, f"❌ No products in `{category_name}`")

    # Pagination
    size = 1
    total_pages = max((total_products + size - 1) // size, 1)

    if page < 1:
        page = total_pages
    if page > total_pages:
        page = 1

    products = await db.get_products_by_category_paginated(category_name, page, size)
    product = products[0]

    card = ui.build_product_photo_card(product, page, total_pages)

    await context.bot.send_photo(
        chat_id=uid,
        photo=card["photo_url"],
        caption=card["caption"],
        reply_markup=card["reply_markup"],
        parse_mode="Markdown",
    )


# ============================================================
# PRODUCT VIEW
# ============================================================

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


# ============================================================
# CART
# ============================================================

async def handle_cart_add(update, context, q, pid, qty):
    uid = _uid(update)
    user_row = await db.get_user_by_telegram_id(uid)
    await db.cart_add_item(user_row["user_id"], pid, qty)
    await q.answer("🛒 Added to cart")


# ============================================================
# ORDERS
# ============================================================

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

    # First item only (single-product orders)
    item = order["items"][0]
    product = await db.get_product_by_id(item["product_id"])

    buyer = await db.get_user_by_id(order["buyer_id"])
    seller = await db.get_user_by_id(order["seller_id"])

    text, kb = ui.build_order_summary(order, product, buyer, seller, role)
    await safe_edit(q, text, kb)


# ============================================================
# WALLET
# ============================================================

async def handle_wallet(update, context, q):
    uid = _uid(update)
    user = await db.get_user_by_telegram_id(uid)
    wallet = await db.get_or_create_wallet(user["user_id"])

    text, kb = ui.build_wallet_dashboard(wallet, user)
    await safe_edit(q, text, kb)


# ============================================================
# ADMIN
# ============================================================

async def handle_admin(update, context, q):
    uid = _uid(update)
    if uid != ADMIN_ID:
        return await q.answer("🚫 Admin only", show_alert=True)

    text, kb = ui.build_admin_panel_menu()
    await safe_edit(q, text, kb)


# ============================================================
# CHECKOUT
# ============================================================

async def start_checkout(update, context, q, pid):
    uid = _uid(update)
    user = await db.get_user_by_telegram_id(uid)

    order = await db.create_single_product_order(user["user_id"], pid)
    text, kb = ui.build_payment_method_menu(order["order_id"], order["total_amount"])

    await safe_edit(q, text, kb)

# ============================================================
# Admin
# ============================================================

async def handle_admin_users(update, context, q, page):
    size = 6
    total = await db.admin_count_users()
    total_pages = max((total + size - 1) // size, 1)
    users = await db.admin_get_users_paginated(page, size)
    text, kb = await ui.build_admin_user_list(users, page, total_pages)
    return await safe_edit(q, text, kb)


async def handle_admin_user_view(update, context, q, uid):
    user = await db.get_user_by_id(uid)
    wallet = await db.get_or_create_wallet(uid)
    text, kb = ui.build_admin_user_view(user, wallet)
    return await safe_edit(q, text, kb)


async def handle_admin_products(update, context, q, page):
    size = 6
    total = await db.admin_count_products()
    total_pages = max((total + size - 1) // size, 1)
    products = await db.admin_get_products_paginated(page, size)
    text, kb = ui.build_admin_product_list(products, page, total_pages)
    return await safe_edit(q, text, kb)


async def handle_admin_product_view(update, context, q, pid):
    product = await db.get_product_by_id(pid)
    card = ui.build_admin_product_view(product)
    await context.bot.send_photo(
        chat_id=_uid(update),
        photo=card["photo_url"],
        caption=card["caption"],
        reply_markup=card["reply_markup"],
        parse_mode="Markdown",
    )


# ============================================================
# CALLBACK ROUTER
# ============================================================

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = q.data

    try:
        await q.answer()
    except:
        pass

    # ---------- MAIN MENU ----------
    if data == "v2:menu:main":
        return await handle_main(update, context, q)

    # ---------- SHOP ----------
    if data == "v2:shop:categories":
        return await handle_categories(update, context, q)

    if data.startswith("v2:shop:cat:"):
        category = data.split(":", 3)[3]
        return await handle_category_page(update, context, q, category, 1)

    if data.startswith("v2:shop:page:"):
        _, _, _, category, page = data.split(":", 4)
        return await handle_category_page(update, context, q, category, int(page))

    if data.startswith("v2:shop:product:"):
        pid = int(data.split(":")[3])
        return await handle_product(update, context, q, pid)

    # ---------- CART ----------
    if data.startswith("v2:cart:add:"):
        _, _, _, pid, qty = data.split(":")
        return await handle_cart_add(update, context, q, int(pid), int(qty))

    # ---------- ORDERS ----------
    if data == "v2:buyer:orders":
        return await handle_orders(update, context, q, 1)

    if data.startswith("v2:buyer:orders_page:"):
        page = int(data.split(":")[3])
        return await handle_orders(update, context, q, page)

    # ---------- ORDER VIEW ----------
    if data.startswith("v2:order:view:"):
        _, _, _, oid, role = data.split(":")
        return await handle_order_view(update, context, q, int(oid), role)

    # ---------- WALLET ----------
    if data in ("v2:wallet:dashboard", "v2:wallet:refresh"):
        return await handle_wallet(update, context, q)

    # ---------- CHECKOUT ----------
    if data.startswith("v2:checkout:"):
        pid = int(data.split(":")[2])
        return await start_checkout(update, context, q, pid)

    # ---------- ADMIN ----------
        # --------------------
    # ADMIN PANEL
    # --------------------
    if data == "v2:admin:panel":
        return await handle_admin(update, context, q)

    if data == "v2:admin:stats":
        stats = await db.admin_get_stats()
        text, kb = ui.build_admin_stats(stats)
        return await safe_edit(q, text, kb)

    # USERS
    if data == "v2:admin:users":
        return await handle_admin_users(update, context, q, 1)

    if data.startswith("v2:admin:users_page:"):
        _, _, _, page = data.split(":")
        return await handle_admin_users(update, context, q, int(page))

    if data.startswith("v2:admin:user_view:"):
        _, _, _, uid = data.split(":")
        return await handle_admin_user_view(update, context, q, int(uid))

    if data.startswith("v2:admin:user_promote:"):
        _, _, _, uid = data.split(":")
        await db.admin_promote_user(int(uid))
        await q.answer("Promoted ✔️")
        return await handle_admin_user_view(update, context, q, int(uid))

    if data.startswith("v2:admin:user_demote:"):
        _, _, _, uid = data.split(":")
        await db.admin_demote_user(int(uid))
        await q.answer("Demoted ✔️")
        return await handle_admin_user_view(update, context, q, int(uid))

    # WALLET ACTIONS
    if data.startswith("v2:admin:wallet_lock:"):
        _, _, _, uid = data.split(":")
        await db.admin_lock_wallet(int(uid))
        await q.answer("Wallet locked 🔒")
        return await handle_admin_user_view(update, context, q, int(uid))

    if data.startswith("v2:admin:wallet_unlock:"):
        _, _, _, uid = data.split(":")
        await db.admin_unlock_wallet(int(uid))
        await q.answer("Wallet unlocked 🔓")
        return await handle_admin_user_view(update, context, q, int(uid))

    # PRODUCTS
    if data == "v2:admin:products":
        return await handle_admin_products(update, context, q, 1)

    if data.startswith("v2:admin:products_page:"):
        _, _, _, page = data.split(":")
        return await handle_admin_products(update, context, q, int(page))

    if data.startswith("v2:admin:product_view:"):
        _, _, _, pid = data.split(":")
        return await handle_admin_product_view(update, context, q, int(pid))

    if data.startswith("v2:admin:product_delete:"):
        _, _, _, pid = data.split(":")
        await db.admin_delete_product(int(pid))
        await q.answer("Deleted ✔️")
        return await handle_admin_products(update, context, q, 1)

    # DISPUTES
    if data == "v2:admin:disputes":
        disputes = await db.admin_get_disputes()
        text, kb = ui.build_admin_dispute_list(disputes)
        return await safe_edit(q, text, kb)


# ============================================================
# MESSAGE HANDLER
# ============================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Use /start to open the marketplace.")


# ============================================================
# MAIN (WINDOWS SAFE)
# ============================================================

def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN missing in .env")
        return

    async def setup():
        await db.init_db()
        logger.info("Database initialised.")

        app = ApplicationBuilder().token(BOT_TOKEN).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(callback_router))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        print("🤖 Marketplace Bot — Running")
        return app

    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = loop.run_until_complete(setup())
    app.run_polling()


if __name__ == "__main__":
    main()
