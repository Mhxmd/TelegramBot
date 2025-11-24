<<<<<<< HEAD
# ==========================
# TELEGRAM MARKETPLACE BOT – MODULAR VERSION
# Buyer + Seller + Chat Relay + Public Chat + Solana Wallet
#
# Requirements:
#   pip install python-telegram-bot==21.* python-dotenv qrcode pillow stripe
#   (and your Solana deps in wallet_utils.py)
#
# Files:
#   bot.py
#   wallet_utils.py
#   modules/storage.py
#   modules/ui.py
#   modules/chat.py
#   modules/seller.py
#   modules/wallet.py
#   modules/notifications.py
# ==========================
=======
# ============================================================
# TELEGRAM MARKETPLACE BOT – V2 (SQL ONLY)
# Fully synced with ui.py (single-file UI) + db.py (Railway)
# Includes: Admin Panel, Seller Panel, Category Browsing, Checkout
# ============================================================
>>>>>>> 782ba07e8a40608c3ad3757f3695bd5066fb2526

import os
import logging
from dotenv import load_dotenv
<<<<<<< HEAD
from telegram import Update
=======
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto
)
>>>>>>> 782ba07e8a40608c3ad3757f3695bd5066fb2526
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

<<<<<<< HEAD
# --- Load env FIRST so getenv works for both BOT_TOKEN and ADMIN_ID ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# our modules
from modules import storage, ui, chat, seller, notifications  # noqa: E402
import modules.wallet_utils as wallet  # noqa: E402

# logging
=======
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
>>>>>>> 782ba07e8a40608c3ad3757f3695bd5066fb2526
logging.basicConfig(
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    level=logging.INFO,
)
<<<<<<< HEAD
logger = logging.getLogger("marketbot")


# ==========================
# COMMANDS
# ==========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Deliver any pending notifications (e.g., reminders sent while user was offline)
    if hasattr(storage, "get_pending_notifications"):
        try:
            pending = storage.get_pending_notifications(user_id)
            if pending:
                for note in pending:
                    try:
                        await update.message.reply_text(note, parse_mode="Markdown")
                    except Exception:
                        pass
                storage.clear_pending_notifications(user_id)
        except Exception:
            # don't block start on inbox errors
            pass

    # anti-spam
    if storage.is_spamming(user_id):
        return

    # ensure user wallet exists (solana)
    try:
        wallet.ensure_user_wallet(user_id)
    except Exception as e:
        logger.warning(f"Wallet init failed for {user_id}: {e}")

    # show main menu
    bal = storage.get_balance(user_id)
    kb, text = ui.build_main_menu(bal)
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")


async def shop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if storage.is_spamming(user_id):
        return
    text, kb = ui.build_shop_keyboard()
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")


# ==========================
# CALLBACK ROUTER
# ==========================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()

    # Always acknowledge quickly to avoid “loading spinner” hanging
    try:
        await q.answer()
    except Exception:
        pass

    try:
        # ---------- MENUS ----------
        if data.startswith("menu:"):
            await ui.on_menu(update, context)
            return

        # ---------- SHOP FLOW ----------
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

        if data.startswith("paynow:"):
            _, sku, qty = data.split(":")
            await ui.show_paynow(update, context, sku, int(qty))
            return

        # Simulated return buttons from fake gateway
        if data.startswith("payconfirm:"):
            order_id = data.split(":", 1)[1]
            from modules.ui import handle_pay_confirm
            await handle_pay_confirm(update, context, order_id)
            return

        if data.startswith("paycancel:"):
            order_id = data.split(":", 1)[1]
            from modules.ui import handle_pay_cancel
            await handle_pay_cancel(update, context, order_id)
            return

        if data == "back_to_shop":
            text, kb = ui.build_shop_keyboard()
            await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
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

        # ---------- CHAT ----------
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

        # ---------- WALLET ----------
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

        # ---------- ADMIN (escrow/disputes) ----------
        if data == "admin:disputes":
            await ui.admin_open_disputes(update, context)
            return

        if data.startswith("admin_refund:"):
            _, oid = data.split(":")
            await ui.admin_refund(update, context, oid)
            return

        if data.startswith("admin_release:"):
            _, oid = data.split(":")
            await ui.admin_release(update, context, oid)
            return

        # Fallback
        logger.info(f"Unhandled callback data: {data}")

    except Exception as e:
        logger.exception("Callback error")
        # IMPORTANT: If the original message was a photo/caption,
        # edit_message_text will 400. ui.* handlers try to handle that.
        # Here we fall back to sending a new message to avoid hard failures.
        try:
            await q.edit_message_text(f"⚠️ Error: {e}\nPlease /start again.")
        except Exception:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_user.id,
                    text=f"⚠️ Error: {e}\nPlease /start again."
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

    # 2) Private thread
    if chat.is_in_private_thread(uid):
        await chat.handle_private_message(update, context, text)
        return

    # 3) Seller flow
    if seller.is_in_seller_flow(uid):
        await seller.handle_seller_flow(update, context, text)
        return

    # 4) Wallet withdraw flow
    if wallet.is_in_withdraw_flow(uid):
        await wallet.handle_withdraw_flow(update, context, text)
        return

    # 5) Otherwise prompt menu
    if text.lower() not in ("/start", "/shop"):
        await msg.reply_text("Type /start to open the menu.")


# ==========================
# ASYNC ERROR HANDLER (PTB v21 needs coroutine)
# ==========================
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        logger.error("Unhandled error", exc_info=context.error)
    except Exception:
        pass


# ==========================
# MAIN
# ==========================
=======
logger = logging.getLogger("marketbot_v2")


# ============================================================
# Helpers
# ============================================================

def _uid(update: Update) -> int:
    return update.effective_user.id


async def safe_edit(q, text, kb=None):
    """
    Safe edit that never attempts to edit photo messages.
    """

    # If message contains photo, send new text message ALWAYS.
    if q.message.photo:
        return await q.message.reply_text(
            text,
            reply_markup=kb,
            parse_mode="Markdown"
        )

    # Try normal edit
    try:
        return await q.edit_message_text(
            text,
            reply_markup=kb,
            parse_mode="Markdown"
        )
    except:
        # Fallback: send new message
        return await q.message.reply_text(
            text,
            reply_markup=kb,
            parse_mode="Markdown"
        )



# ============================================================
# /start
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = _uid(update)
    username = update.effective_user.username or f"user_{uid}"

    # ensure user exists
    user_row = await db.get_or_create_user(uid, username)
    await db.get_or_create_wallet(user_row["user_id"])

    # show main menu
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
# SHOP — Categories
# ============================================================

async def handle_categories(update, context, q):
    cats = await db.get_all_categories()
    if not cats:
        return await safe_edit(q, "❌ No categories available.")

    text, kb = ui.build_category_menu(cats)
    await safe_edit(q, text, kb)


# ============================================================
# SHOP — Category Page
# ============================================================

async def handle_category_page(update, context, q, category_name, page):
    uid = _uid(update)

    total_products = await db.count_products_by_category(category_name)
    if total_products == 0:
        return await safe_edit(q, f"❌ No products in `{category_name}`")

    size = 1
    total_pages = max((total_products + size - 1) // size, 1)

    # wrap pagination
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
# CART — Add to Cart
# ============================================================

async def handle_cart_add(update, context, q, pid, qty):
    uid = _uid(update)
    user_row = await db.get_user_by_telegram_id(uid)
    await db.cart_add_item(user_row["user_id"], pid, qty)
    await q.answer("🛒 Added to cart")


# ============================================================
# CART — View Cart
# ============================================================

async def handle_cart_view(update, context, q):
    uid = _uid(update)
    user = await db.get_user_by_telegram_id(uid)

    text, kb = await ui.build_cart_view(user["user_id"])
    await safe_edit(q, text, kb)


# ============================================================
# ORDERS — List
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


# ============================================================
# ORDER VIEW — Detailed
# ============================================================

async def handle_order_view(update, context, q, oid, role):
    order = await db.get_order_by_id(oid)
    if not order:
        return await safe_edit(q, "❌ Order not found.")

    item = order["items"][0]  # single-item for now
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
# CHECKOUT (Single Product)
# ============================================================

async def start_checkout(update, context, q, pid):
    uid = _uid(update)
    user = await db.get_user_by_telegram_id(uid)

    order = await db.create_single_product_order(user["user_id"], pid)
    text, kb = ui.build_payment_method_menu(order["order_id"], order["total_amount"])

    await safe_edit(q, text, kb)


# ============================================================
# CHECKOUT (From Cart)
# ============================================================

async def start_checkout_cart(update, context, q):
    uid = _uid(update)
    user = await db.get_user_by_telegram_id(uid)

    order = await db.create_order_from_cart(user["user_id"])
    if not order:
        return await safe_edit(q, "🛒 Your cart is empty.")

    text, kb = ui.build_payment_method_menu(order["order_id"], order["total_amount"])
    await safe_edit(q, text, kb)


# ============================================================
# ADMIN — USERS
# ============================================================

async def handle_admin(update, context, q):
    text, kb = ui.build_admin_panel_menu()
    await safe_edit(q, text, kb)


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


# ============================================================
# ADMIN — PRODUCTS
# ============================================================

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
# SELLER PANEL
# ============================================================

async def handle_seller_dashboard(update, context, q):
    text, kb = ui.build_seller_dashboard()
    await safe_edit(q, text, kb)


async def handle_seller_products(update, context, q):
    uid = _uid(update)
    user = await db.get_user_by_telegram_id(uid)

    products = await db.get_seller_products(user["user_id"])
    text, kb = ui.build_seller_product_list(products)
    await safe_edit(q, text, kb)


async def handle_seller_product_view(update, context, q, pid):
    product = await db.get_product_by_id(pid)
    card = ui.build_seller_product_card(product)

    await context.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo=card["photo_url"],
        caption=card["text"],
        reply_markup=card["reply_markup"],
        parse_mode="Markdown",
    )


async def handle_seller_delete_product(update, context, q, pid):
    await db.seller_delete_product(pid)
    await safe_edit(
        q,
        "❌ Product deleted.",
        ui.build_seller_after_delete_menu()
    )


# ============================================================
# ADD PRODUCT FLOW (Seller)
# ============================================================

async def handle_add_product_text(update, context):
    """Handles user text for adding new product (multi-step form)."""
    uid = update.effective_user.id

    if "addprod" not in context.user_data:
        return 

    step = context.user_data["addprod"]["step"]
    data = context.user_data["addprod"]

    # ------------------ Step 1: Title ------------------
    if step == 1:
        data["title"] = update.message.text
        data["step"] = 2
        return await update.message.reply_text(
            "📝 Enter product *description*:",
            parse_mode="Markdown"
        )

    # ------------------ Step 2: Description ------------------
    if step == 2:
        data["desc"] = update.message.text
        data["step"] = 3
        return await update.message.reply_text(
            "💵 Enter *price* (numbers only):",
            parse_mode="Markdown"
        )

    # ------------------ Step 3: Price ------------------
    if step == 3:
        try:
            data["price"] = float(update.message.text)
        except:
            return await update.message.reply_text("❌ Invalid price. Try again.")
        data["step"] = 4
        return await update.message.reply_text("📦 Enter *stock quantity*:")

    # ------------------ Step 4: Quantity ------------------
    if step == 4:
        try:
            data["qty"] = int(update.message.text)
        except:
            return await update.message.reply_text("❌ Invalid quantity. Try again.")
        data["step"] = 5
        return await update.message.reply_text(
            "🏷 Enter *category ID* (number):",
            parse_mode="Markdown"
        )

    # ------------------ Step 5: Category ------------------
    if step == 5:
        try:
            data["category_id"] = int(update.message.text)
        except:
            return await update.message.reply_text("❌ Invalid category ID.")
        
        # Create product
        user = await db.get_user_by_telegram_id(uid)
        new_prod = await db.create_product(
            user["user_id"],
            data["title"],
            data["desc"],
            data["price"],
            data["qty"],
            data["category_id"]
        )

        context.user_data.pop("addprod")
        return await update.message.reply_text(
            f"✅ Product *{new_prod['title']}* created!\n"
            "You can now add images via seller panel.",
            parse_mode="Markdown"
        )


# ============================================================
# CALLBACK ROUTER (COMPLETE + CLEAN)
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

    # ------------------------------------------------------------
    # SELLER — Add Product (Start Flow)
    # ------------------------------------------------------------
# --- SELLER: Add Product ---
    if data == "v2:seller:add":
        uid = _uid(update)
        user = await db.get_user_by_telegram_id(uid)

    # Start the multi-step add-product form
        context.user_data["addprod"] = {
            "step": 1,
            "title": "",
            "desc": "",
            "price": 0,
            "qty": 0,
            "category_id": 0,
        }

        await safe_edit(
        q,
        "📝 Enter *product title*: ",
        None
        )
        return



    # ---------- PUBLIC FEED ----------
    if data.startswith("v2:feed:all:"):
        page = int(data.split(":")[3])

        size = 5
        total = await db.count_all_products()
        total_pages = max((total + size - 1) // size, 1)

        # wrap pagination
        if page < 1:
            page = total_pages
        if page > total_pages:
            page = 1

        products = await db.get_all_products_paginated(page, size)
        text, kb = ui.build_public_feed(products, page, total_pages)

        return await safe_edit(q, text, kb)

    # ---------- CATEGORY / SHOP ----------
    if data == "v2:shop:categories":
        return await handle_categories(update, context, q)

    if data.startswith("v2:shop:cat:"):
        cat = data.split(":", 3)[3]
        return await handle_category_page(update, context, q, cat, 1)

    if data.startswith("v2:shop:page:"):
        _, _, _, cat, page = data.split(":")
        return await handle_category_page(update, context, q, cat, int(page))

    if data.startswith("v2:shop:product:"):
        pid = int(data.split(":")[3])
        return await handle_product(update, context, q, pid)

    # ---------- CART ----------
    if data == "v2:cart:view":
        return await handle_cart_view(update, context, q)

    if data.startswith("v2:cart:add:"):
        _, _, _, pid, qty = data.split(":")
        return await handle_cart_add(update, context, q, int(pid), int(qty))

    if data == "v2:checkout_cart":
        return await start_checkout_cart(update, context, q)

    if data == "v2:cart:clear":
        uid = _uid(update)
        user = await db.get_user_by_telegram_id(uid)
        await db.cart_clear(user["user_id"])
        await q.answer("Cart cleared 🧹")
        return await handle_cart_view(update, context, q)


    # ---------- ORDERS ----------
    if data == "v2:buyer:orders":
        return await handle_orders(update, context, q, 1)

    if data.startswith("v2:buyer:orders_page:"):
        page = int(data.split(":")[3])
        return await handle_orders(update, context, q, page)

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

    # ============================================================
    # SELLER PANEL ROUTES
    # ============================================================

    if data == "v2:seller:dashboard":
        return await handle_seller_dashboard(update, context, q)

# ============================================================
# SELLER — Become Seller
# ============================================================

    # ---------- SELLER — Become Seller ----------
    if data == "v2:seller:become":
        uid = _uid(update)
        user = await db.get_user_by_telegram_id(uid)

    # Promote
        await db.promote_to_seller(user["user_id"])
        await q.answer("🎉 You are now a seller!")

    # Refresh main menu (IMPORTANT: use reply, not edit)
        text, kb = await ui.build_main_menu(user["user_id"])
        return await safe_edit(q, text, kb)



    # ============================================================
    # ADMIN ROUTES
    # ============================================================

    if data == "v2:admin:panel":
        return await handle_admin(update, context, q)

    if data == "v2:admin:users":
        return await handle_admin_users(update, context, q, 1)

    if data.startswith("v2:admin:users_page:"):
        page = int(data.split(":")[3])
        return await handle_admin_users(update, context, q, page)

    if data.startswith("v2:admin:user_view:"):
        uid = int(data.split(":")[3])
        return await handle_admin_user_view(update, context, q, uid)

    if data.startswith("v2:admin:user_promote:"):
        uid = int(data.split(":")[3])
        await db.admin_promote_user(uid)
        await q.answer("Promoted ✔️")
        return await handle_admin_user_view(update, context, q, uid)

    if data.startswith("v2:admin:user_demote:"):
        uid = int(data.split(":")[3])
        await db.admin_demote_user(uid)
        await q.answer("Demoted ✔️")
        return await handle_admin_user_view(update, context, q, uid)

    if data.startswith("v2:admin:wallet_lock:"):
        uid = int(data.split(":")[3])
        await db.admin_lock_wallet(uid)
        await q.answer("Wallet locked 🔒")
        return await handle_admin_user_view(update, context, q, uid)

    if data.startswith("v2:admin:wallet_unlock:"):
        uid = int(data.split(":")[3])
        await db.admin_unlock_wallet(uid)
        await q.answer("Wallet unlocked 🔓")
        return await handle_admin_user_view(update, context, q, uid)

    # PRODUCTS
    if data == "v2:admin:products":
        return await handle_admin_products(update, context, q, 1)

    if data.startswith("v2:admin:products_page:"):
        page = int(data.split(":")[3])
        return await handle_admin_products(update, context, q, page)

    if data.startswith("v2:admin:product_view:"):
        pid = int(data.split(":")[3])
        return await handle_admin_product_view(update, context, q, pid)

    if data.startswith("v2:admin:product_delete:"):
        pid = int(data.split(":")[3])
        await db.admin_delete_product(pid)
        await q.answer("Deleted ✔️")
        return await handle_admin_products(update, context, q, 1)


# ============================================================
# MESSAGE HANDLER
# ============================================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await handle_add_product_text(update, context)


# ============================================================
# MAIN (WINDOWS SAFE)
# ============================================================

>>>>>>> 782ba07e8a40608c3ad3757f3695bd5066fb2526
def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN missing in .env")
        return

<<<<<<< HEAD
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("shop", shop_cmd))

    # callback buttons
    app.add_handler(CallbackQueryHandler(callback_router))

    # text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # errors (must be async)
    app.add_error_handler(on_error)

    print("🤖 Marketplace Bot running — Ctrl+C to stop")
=======
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
>>>>>>> 782ba07e8a40608c3ad3757f3695bd5066fb2526
    app.run_polling()


if __name__ == "__main__":
    main()
