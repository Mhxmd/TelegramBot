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

# --- Load env FIRST so getenv works for both BOT_TOKEN and ADMIN_ID ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# our modules
from modules import storage, ui, chat, seller, shopping_cart  # noqa: E402
import modules.wallet_utils as wallet  # noqa: E402

# logging
logging.basicConfig(
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    level=logging.INFO,
)
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

        # ---------- SEARCH BUTTON ----------
        if data == "shop:search":
            await ui.ask_search(update, context)
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

        if data.startswith("stripe_cart:"):
            _, total = data.split(":")
            return await ui.stripe_cart_checkout(update, context, total)

        if data.startswith("paynow_cart:"):
            _, total = data.split(":")
            return await ui.show_paynow_cart(update, context, total)
        

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
        
        # ---------- SHOPPING CART ----------
        if data.startswith("cart_add:"):
            _, sku = data.split(":")
            await shopping_cart.add_item(update, context, sku)
            return await shopping_cart.view_cart(update, context)

        if data.startswith("cart:remove:"):
            _, _, sku = data.split(":")
            await shopping_cart.remove_item(update, context, sku)
            return

        if data.startswith("cart:addqty:"):
            _, _, sku = data.split(":")
            await shopping_cart.change_quantity(update, context, sku, +1)
            return

        if data.startswith("cart:subqty:"):
            _, _, sku = data.split(":")
            await shopping_cart.change_quantity(update, context, sku, -1)
            return

        if data == "cart:view":
            return await shopping_cart.view_cart(update, context)

        if data == "cart:checkout_all":
            return await ui.cart_checkout_all(update, context)

        if data == "cart:confirm_payment":
            return await shopping_cart.confirm_payment(update, context)

        if data == "cart:cancel":
            return await shopping_cart.view_cart(update, context)



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
    
    # ---------------- HANDLE SEARCH TEXT ----------------
    if context.user_data.get("awaiting_search"):
        context.user_data["awaiting_search"] = False
        results = ui.search_products_by_name(text)
        await ui.show_search_results(update, context, results)
        return



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
def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN missing in .env")
        return

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
    app.run_polling()


if __name__ == "__main__":
    main()
