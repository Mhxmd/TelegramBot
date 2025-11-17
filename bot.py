# ==========================
# TELEGRAM MARKETPLACE BOT – v2 HYBRID
# Uses:
# - New ERD-based marketplace (PostgreSQL via db.py)
# - Old JSON-based features (shop, cart, search, filters, chat, seller, wallet_utils)
# ==========================

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

# --- Load env FIRST ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")

# our modules
from modules import storage, ui, chat, seller, notifications  # noqa: E402
import modules.wallet_utils as wallet  # noqa: E402
import modules.db as db  # ERD-based PostgreSQL layer  # noqa: E402

# logging
logging.basicConfig(
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("marketbot_v2")


# ==========================
# SMALL HELPERS
# ==========================

def _uid(update: Update) -> int:
    return update.effective_user.id


async def _send_or_edit(q, text, kb=None, parse_mode="Markdown"):
    """
    Safely edit callback message, or send a new one if edit fails.
    """
    try:
        await q.edit_message_text(text, reply_markup=kb, parse_mode=parse_mode)
    except Exception:
        try:
            await q.message.reply_text(text, reply_markup=kb, parse_mode=parse_mode)
        except Exception as e:
            logger.warning(f"Failed to send/edit message: {e}")


# ==========================
# COMMANDS
# ==========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = _uid(update)
    tg_user = update.effective_user
    username = tg_user.username or f"user_{user_id}"

    # Deliver any pending notifications (if you use notifications.py)
    if hasattr(notifications, "get_pending_notifications"):
        try:
            pending = notifications.get_pending_notifications(user_id)
            if pending:
                for note in pending:
                    try:
                        await update.message.reply_text(note, parse_mode="Markdown")
                    except Exception:
                        pass
                notifications.clear_pending_notifications(user_id)
        except Exception:
            pass

    # anti-spam via storage JSON system
    if storage.is_spamming(user_id):
        return

    # legacy Solana wallet module (JSON-based) – keep as additional helper
    try:
        wallet.ensure_user_wallet(user_id)
    except Exception as e:
        logger.warning(f"wallet_utils init failed for {user_id}: {e}")

    # --- NEW: ensure user & wallet exist in the SQL DB (ERD-based) ---
    try:
        user_row = await db.get_or_create_user(telegram_id=user_id, username=username)
        wallet_row = await db.get_or_create_wallet(user_id=user_row["user_id"])
    except Exception as e:
        logger.exception(f"DB init failed for user {user_id}: {e}")
        # Fallback: use old main menu
        bal = storage.get_balance(user_id)
        kb, text = ui.build_main_menu(bal)
        await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
        return

    role = user_row.get("role", "buyer")
    verified = user_row.get("verification_status", False)
    balance = wallet_row.get("balance", 0.0)

    # --- NEW: role-aware v2 main menu (ERD marketplace) ---
    text, kb = ui.build_role_main_menu(
        role=role,
        balance=balance,
        verification_status=verified,
    )
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")


async def shop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Legacy /shop command – uses old JSON-based shop.
    """
    user_id = _uid(update)
    if storage.is_spamming(user_id):
        return
    text, kb = ui.build_shop_keyboard()
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🧾 *Marketplace Bot v2*\n\n"
        "Commands:\n"
        "/start – Open main marketplace menu (ERD / SQL)\n"
        "/shop – Open legacy JSON shop (hoodies, etc.)\n"
        "/help – This help\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


# ==========================
# v2 MARKETPLACE HANDLERS (ERD / SQL)
# ==========================

async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, q):
    uid = _uid(update)
    user_row = await db.get_user_by_telegram_id(uid)
    if not user_row:
        tg_user = update.effective_user
        user_row = await db.get_or_create_user(uid, tg_user.username or f"user_{uid}")

    wallet_row = await db.get_or_create_wallet(user_row["user_id"])
    role = user_row.get("role", "buyer")
    verified = user_row.get("verification_status", False)
    balance = wallet_row.get("balance", 0.0)

    text, kb = ui.build_role_main_menu(
        role=role,
        balance=balance,
        verification_status=verified,
    )
    await _send_or_edit(q, text, kb)


async def handle_shop_categories(update: Update, context: ContextTypes.DEFAULT_TYPE, q):
    categories = await db.get_all_categories()
    if not categories:
        await _send_or_edit(q, "🛍️ No categories or products yet.", None)
        return
    text, kb = ui.build_category_menu(categories)
    await _send_or_edit(q, text, kb)


async def handle_shop_category_page(update: Update, context: ContextTypes.DEFAULT_TYPE, q,
                                    category: str, page: int, page_size: int = 1):
    uid = _uid(update)
    total_count = await db.count_products_by_category(category)
    if total_count == 0:
        await _send_or_edit(q, f"🛍️ No products in `{category}` yet.", None)
        return

    total_pages = max((total_count + page_size - 1) // page_size, 1)
    if page < 1:
        page = total_pages
    if page > total_pages:
        page = 1

    products = await db.get_products_by_category_paginated(category, page, page_size)
    if not products:
        await _send_or_edit(q, f"🛍️ No products found for page {page}.", None)
        return

    product = products[0]
    card = ui.build_product_photo_card(product, page=page, total_pages=total_pages)

    try:
        if q.message.photo:
            await q.edit_message_caption(
                caption=card["caption"],
                reply_markup=card["reply_markup"],
                parse_mode="Markdown",
            )
        else:
            await q.message.delete()
            await context.bot.send_photo(
                chat_id=uid,
                photo=card["photo_url"],
                caption=card["caption"],
                reply_markup=card["reply_markup"],
                parse_mode="Markdown",
            )
    except Exception:
        await context.bot.send_photo(
            chat_id=uid,
            photo=card["photo_url"],
            caption=card["caption"],
            reply_markup=card["reply_markup"],
            parse_mode="Markdown",
        )


async def handle_product_view(update: Update, context: ContextTypes.DEFAULT_TYPE, q, product_id: int):
    uid = _uid(update)
    product = await db.get_product_by_id(product_id)
    if not product:
        await _send_or_edit(q, "❌ Product not found.", None)
        return

    card = ui.build_product_photo_card(product, page=1, total_pages=1)
    await context.bot.send_photo(
        chat_id=uid,
        photo=card["photo_url"],
        caption=card["caption"],
        reply_markup=card["reply_markup"],
        parse_mode="Markdown",
    )


async def handle_cart_add(update: Update, context: ContextTypes.DEFAULT_TYPE, q, product_id: int, qty: int):
    uid = _uid(update)
    user_row = await db.get_user_by_telegram_id(uid)
    if not user_row:
        await _send_or_edit(q, "❌ Please /start first.", None)
        return

    await db.cart_add_item(user_row["user_id"], product_id, qty)
    await q.answer("🛒 Added to cart", show_alert=False)


async def handle_buyer_orders(update: Update, context: ContextTypes.DEFAULT_TYPE, q, page: int, page_size: int = 5):
    uid = _uid(update)
    user_row = await db.get_user_by_telegram_id(uid)
    if not user_row:
        await _send_or_edit(q, "❌ Please /start first.", None)
        return

    user_id = user_row["user_id"]
    total_count = await db.count_orders_by_buyer(user_id)
    total_pages = max((total_count + page_size - 1) // page_size, 1)
    if page < 1:
        page = total_pages
    if page > total_pages:
        page = 1

    orders = await db.get_orders_by_buyer_paginated(user_id, page, page_size)
    text, kb = ui.build_orders_list(orders, for_role="buyer", page=page, total_pages=total_pages)
    await _send_or_edit(q, text, kb)


async def handle_order_view(update: Update, context: ContextTypes.DEFAULT_TYPE, q, order_id: int, role: str):
    order = await db.get_order_by_id(order_id)
    if not order:
        await _send_or_edit(q, "❌ Order not found.", None)
        return

    product = await db.get_product_by_id(order["product_id"])
    buyer = await db.get_user_by_id(order["buyer_id"])
    seller_row = await db.get_user_by_id(order["seller_id"])

    text, kb = ui.build_order_summary(order, product, buyer, seller_row, for_role=role)
    await _send_or_edit(q, text, kb)


async def handle_wallet_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE, q):
    uid = _uid(update)
    user_row = await db.get_user_by_telegram_id(uid)
    if not user_row:
        await _send_or_edit(q, "❌ Please /start first.", None)
        return

    wallet_row = await db.get_or_create_wallet(user_row["user_id"])
    text, kb = ui.build_wallet_dashboard(wallet_row, user_row)
    await _send_or_edit(q, text, kb)


async def handle_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE, q):
    uid = _uid(update)
    if uid != ADMIN_ID:
        await q.answer("🚫 Admin only", show_alert=True)
        return

    text, kb = ui.build_admin_panel_menu()
    await _send_or_edit(q, text, kb)


# ==========================
# CALLBACK ROUTER
# ==========================

async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()
    uid = _uid(update)

    # ack quickly
    try:
        await q.answer()
    except Exception:
        pass

    try:
        # ============================================
        # NEW v2 MARKETPLACE CALLBACKS (ERD / SQL)
        # ============================================

        # main menu
        if data in ("menu:main", "main_menu", "v2:menu:main"):
            await handle_main_menu(update, context, q)
            return

        # shop categories
        if data == "v2:shop:categories":
            await handle_shop_categories(update, context, q)
            return

        # category selected
        if data.startswith("v2:shop:cat:"):
            _, _, _, category = data.split(":", 3)
            await handle_shop_category_page(update, context, q, category, page=1)
            return

        # change page in category carousel
        if data.startswith("v2:shop:page:"):
            _, _, _, category, page_str = data.split(":", 4)
            await handle_shop_category_page(update, context, q, category, int(page_str))
            return

        # open product by id
        if data.startswith("v2:shop:product:"):
            _, _, _, pid_str = data.split(":", 3)
            await handle_product_view(update, context, q, int(pid_str))
            return

        # add to cart (SQL-based)
        if data.startswith("v2:cart:add:"):
            _, _, _, pid_str, qty_str = data.split(":", 4)
            await handle_cart_add(update, context, q, int(pid_str), int(qty_str))
            return

        # buyer orders
        if data == "v2:buyer:orders":
            await handle_buyer_orders(update, context, q, page=1)
            return

        if data.startswith("v2:buyer:orders_page:"):
            _, _, _, page_str = data.split(":", 3)
            await handle_buyer_orders(update, context, q, page=int(page_str))
            return

        # order view
        if data.startswith("v2:order:view:"):
            # v2:order:view:{order_id}:{role}
            _, _, _, oid_str, role = data.split(":", 4)
            await handle_order_view(update, context, q, int(oid_str), role)
            return

        # wallet
        if data in ("v2:wallet:dashboard", "v2:wallet:refresh"):
            await handle_wallet_dashboard(update, context, q)
            return

        # admin panel
        if data == "v2:admin:panel":
            await handle_admin_panel(update, context, q)
            return

        # ============================================
        # LEGACY CALLBACKS (JSON-BASED)
        # ============================================

        # ---------- MENUS ----------
        if data.startswith("menu:"):
            await ui.on_menu(update, context)
            return

        # ---------- SHOP ----------
        if data.startswith("buy:"):
            _, sku, qty = data.split(":")
            await ui.on_buy(update, context, sku, int(qty))
            return

        if data.startswith("qty:"):
            _, sku, qty = data.split(":")
            await ui.on_qty(update, context, sku, int(qty))
            return

        if data.startswith("checkout:"):
            _, sku, qty = data.split(":")
            await ui.on_checkout(update, context, sku, int(qty))
            return

        if data.startswith("stripe:"):
            _, sku, qty = data.split(":")
            await ui.create_stripe_checkout(update, context, sku, int(qty))
            return

        if data == "back_to_shop":
            text, kb = ui.build_shop_keyboard()
            try:
                await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
            except Exception:
                await context.bot.send_message(
                    uid, text, reply_markup=kb, parse_mode="Markdown"
                )
            return

        # ---------- CART (legacy JSON cart) ----------
        if data == "cart:view":
            await ui.cart_view(update, context)
            return

        if data.startswith("cart:add:"):
            _, _, sku, qty = data.split(":")
            await ui.cart_add(update, context, sku, int(qty))
            return

        if data.startswith("cart:inc:"):
            _, _, sku = data.split(":")
            await ui.cart_inc(update, context, sku)
            return

        if data.startswith("cart:dec:"):
            _, _, sku = data.split(":")
            await ui.cart_dec(update, context, sku)
            return

        if data.startswith("cart:remove:"):
            _, _, sku = data.split(":")
            await ui.cart_remove(update, context, sku)
            return

        if data == "cart:clear":
            await ui.cart_clear(update, context)
            return

        if data.startswith("cart:checkout_one:"):
            _, _, sku = data.split(":")
            await ui.cart_checkout_one(update, context, sku)
            return

        if data == "cart:checkout_all":
            await ui.cart_checkout_all(update, context)
            return

        # ---------- SEARCH ----------
        if data == "search:menu":
            msg, kb = ui.build_search_menu()
            try:
                await q.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
            except Exception:
                await context.bot.send_message(
                    uid, msg, reply_markup=kb, parse_mode="Markdown"
                )
            return

        if data == "search:ask":
            state = storage.user_flow_state.setdefault(uid, {})
            state["search_mode"] = True
            txt = (
                "🔎 *Search mode*\n\nSend me your keywords "
                "(e.g. `hoodie`, `cap`, `cat plush`)."
            )
            try:
                await q.edit_message_text(txt, parse_mode="Markdown")
            except Exception:
                await context.bot.send_message(uid, txt, parse_mode="Markdown")
            return

        if data == "search:clear":
            state = storage.user_flow_state.setdefault(uid, {})
            state.pop("search_mode", None)
            text, kb = ui.build_shop_keyboard()
            try:
                await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
            except Exception:
                await context.bot.send_message(
                    uid, text, reply_markup=kb, parse_mode="Markdown"
                )
            return

        # ---------- FILTER ----------
        if data == "filter:menu":
            txt, kb = ui.build_filter_menu()
            try:
                await q.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            except Exception:
                await context.bot.send_message(
                    uid, txt, reply_markup=kb, parse_mode="Markdown"
                )
            return

        if data.startswith("filter:apply:"):
            code = data.split("filter:apply:", 1)[1]
            items = ui.apply_filter(code)
            txt, kb = ui.build_shop_keyboard(filtered_items=items)
            try:
                await q.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            except Exception:
                await context.bot.send_message(
                    uid, txt, reply_markup=kb, parse_mode="Markdown"
                )
            return

        # ---------- SELLER ----------
        if data.startswith("sell:list"):
            await seller.show_seller_listings(update, context)
            return

        if data.startswith("sell:remove_confirm:"):
            _, _, sku = data.split(":")
            await seller.confirm_remove_listing(update, context, sku)
            return

        if data.startswith("sell:remove_do:"):
            _, _, sku = data.split(":")
            await seller.do_remove_listing(update, context, sku)
            return

        # ---------- PRIVATE CHAT ----------
        if data.startswith("contact:"):
            _, sku, seller_id = data.split(":")
            await chat.on_contact_seller(update, context, sku, int(seller_id))
            return

        if data.startswith("chat:open:"):
            _, _, thread_id = data.split(":")
            await chat.on_chat_open(update, context, thread_id)
            return

        if data == "chat:exit":
            await chat.on_chat_exit(update, context)
            return

        # ---------- PUBLIC CHAT ----------
        if data == "chat:public_open":
            await chat.on_public_chat_open(update, context)
            return

        # ---------- WALLET UTILS (legacy) ----------
        if data == "wallet:show_sol":
            await wallet.show_sol_address(update, context)
            return

        if data == "wallet:withdraw":
            await wallet.start_withdraw_flow(update, context)
            return

        if data == "wallet:deposit":
            await wallet.show_deposit_info(update, context)
            return

        # ---------- FUNCTIONS / HELP ----------
        if data == "menu:functions":
            await ui.show_functions_menu(update, context)
            return

        if data == "noop":
            return

        logger.info(f"Unhandled callback data: {data}")

    except Exception as e:
        logger.exception("Callback error")
        try:
            await q.edit_message_text(f"⚠️ Error: {e}\nPlease /start again.")
        except Exception:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"⚠️ Error: {e}\nPlease /start again.",
                )
            except Exception:
                pass


# ==========================
# MESSAGE HANDLER
# ==========================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message
    text = (msg.text or "").strip()
    uid = user.id

    # 1) Public chat
    if chat.is_in_public_chat(uid):
        await chat.handle_public_message(update, context, text)
        return

    # 2) Private chat thread
    if chat.is_in_private_thread(uid):
        await chat.handle_private_message(update, context, text)
        return

    # 3) Seller listing flow
    if seller.is_in_seller_flow(uid):
        await seller.handle_seller_flow(update, context, text)
        return

    # 4) Wallet withdraw flow (legacy)
    if wallet.is_in_withdraw_flow(uid):
        await wallet.handle_withdraw_flow(update, context, text)
        return

    # 5) Search mode (legacy shop)
    state = storage.user_flow_state.setdefault(uid, {})
    if state.get("search_mode"):
        state.pop("search_mode", None)
        items = ui.search_items(text)
        txt, kb = ui.build_shop_keyboard(filtered_items=items, search_query=text)
        await msg.reply_text(txt, reply_markup=kb, parse_mode="Markdown")
        return

    # 6) Default
    if text.lower() not in ("/start", "/shop", "/help"):
        await msg.reply_text("Type /start to open the marketplace, or /shop for the old store.")


# ==========================
# ERROR HANDLER
# ==========================

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled error", exc_info=context.error)


# ==========================
# APP STARTUP (DB INIT)
# ==========================

async def on_startup(app):
    await db.init_db()
    logger.info("Database pool initialised.")


# ==========================
# MAIN
# ==========================

def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN missing in .env")
        return

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(on_startup)
        .build()
    )

    # commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("shop", shop_cmd))
    app.add_handler(CommandHandler("help", help_cmd))

    # callback buttons
    app.add_handler(CallbackQueryHandler(callback_router))

    # text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # errors
    app.add_error_handler(on_error)

    print("🤖 Marketplace Bot v2 running — Ctrl+C to stop")
    app.run_polling()


if __name__ == "__main__":
    main()
