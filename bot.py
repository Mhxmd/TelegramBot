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

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# our modules
from modules import storage, ui, chat, seller, notifications
import modules.wallet_utils as wallet


# load env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

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
    # deliver any pending messages
    pending = storage.get_pending_notifications(user_id)
    if pending:
        for note in pending:
            try:
                await update.message.reply_text(note, parse_mode="Markdown")
            except Exception:
                pass
        storage.clear_pending_notifications(user_id)
   

    # anti-spam
    if storage.is_spamming(user_id):
        return

    # ensure user wallet exists (solana)
    wallet.ensure_user_wallet(user_id)

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
    await q.answer()
    data = q.data or ""

    try:
        # ---------- MENUS ----------
        if data.startswith("menu:"):
            await ui.on_menu(update, context)

        # ---------- SHOP FLOW ----------
        elif data.startswith("buy:"):
            _, sku, qty = data.split(":")
            await ui.on_buy(update, context, sku, int(qty))

        elif data.startswith("qty:"):
            _, sku, qty = data.split(":")
            await ui.on_qty(update, context, sku, int(qty))

        elif data.startswith("paynow_sim_success:"):
            _, name, qty = data.split(":")
            await update.callback_query.edit_message_text(
                f"✅ *Payment simulated for {name} x{qty}*\nSeller will verify shortly.",
                parse_mode="Markdown"
            )
        
        elif data.startswith("payconfirm:"):
            order_id = data.split(":")[1]
            from modules.ui import handle_pay_confirm
            await handle_pay_confirm(update, context, order_id)

        elif data.startswith("paycancel:"):
            order_id = data.split(":")[1]
            from modules.ui import handle_pay_cancel
            await handle_pay_cancel(update, context, order_id)


        elif data.startswith("stripe:"):
            _, sku, qty = data.split(":")
            await ui.create_stripe_checkout(update, context, sku, int(qty))

        elif data.startswith("paynow:"):
            _, sku, qty = data.split(":")
            await ui.show_paynow(update, context, sku, int(qty))

        elif data.startswith("ship:"):
            _, order_id = data.split(":")
            from modules.ui import handle_mark_shipped
            await handle_mark_shipped(update, context, order_id)

        elif data.startswith("release:"):
            _, order_id = data.split(":")
            from modules.ui import handle_release_payment
            await handle_release_payment(update, context, order_id)

        elif data.startswith("dispute:"):
            _, order_id = data.split(":")
            from modules.ui import handle_dispute_case
            await handle_dispute_case(update, context, order_id)


        elif data == "back_to_shop":
            text, kb = ui.build_shop_keyboard()
            await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

        # ---------- SELLER ----------
        elif data.startswith("sell:list"):
            await seller.show_seller_listings(update, context)

        elif data.startswith("sell:remove_confirm:"):
            _, _, sku = data.split(":")
            await seller.confirm_remove_listing(update, context, sku)

        elif data.startswith("sell:remove_do:"):
            _, _, sku = data.split(":")
            await seller.do_remove_listing(update, context, sku)
        
        # ---------- CHAT ----------
        elif data.startswith("contact:"):
            # buyer taps "Contact Seller"
            _, sku, seller_id = data.split(":")
            await chat.on_contact_seller(update, context, sku, int(seller_id))

        elif data.startswith("chat:open:"):
            _, _, thread_id = data.split(":")
            await chat.on_chat_open(update, context, thread_id)

        elif data == "chat:exit":
            await chat.on_chat_exit(update, context)

        # ---------- PUBLIC CHAT ----------
        elif data == "chat:public_open":
            await chat.on_public_chat_open(update, context)

        # ---------- WALLET ----------
        elif data == "wallet:show_sol":
            await wallet.show_sol_address(update, context)

        elif data == "wallet:withdraw":
            await wallet.start_withdraw_flow(update, context)

        elif data == "wallet:deposit":
            await wallet.show_deposit_info(update, context)

        # ---------- FUNCTIONS / HELP ----------
        elif data == "menu:functions":
            await ui.show_functions_menu(update, context)

        elif data == "noop":
            pass

        # ---------- Admin ---------- #
        elif data == "admin:disputes":
            return await ui.admin_open_disputes(update, context)

        elif data.startswith("admin_refund:"):
            _, oid = data.split(":")
            return await ui.admin_refund(update, context, oid)

        elif data.startswith("admin_release:"):
            _, oid = data.split(":")
            return await ui.admin_release(update, context, oid)


    except Exception as e:
        logger.exception("Callback error")
        try:
            await q.edit_message_text(f"⚠️ Error: {e}\nPlease /start again.")
        except Exception:
            pass

       

# ==========================
# MESSAGE HANDLER
# routes:
# - active private chat
# - active public chat
# - seller add listing flow
# - wallet withdraw flow
# ==========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message
    text = (msg.text or "").strip()
    uid = user.id

    # 1) if user is in PUBLIC CHAT
    if chat.is_in_public_chat(uid):
        await chat.handle_public_message(update, context, text)
        return

    # 2) if user is in PRIVATE THREAD
    if chat.is_in_private_thread(uid):
        await chat.handle_private_message(update, context, text)
        return

    # 3) if user is in SELLER FLOW
    if seller.is_in_seller_flow(uid):
        await seller.handle_seller_flow(update, context, text)
        return

    # 4) if user is in WITHDRAW flow
    if wallet.is_in_withdraw_flow(uid):
        await wallet.handle_withdraw_flow(update, context, text)
        return

    # 5) otherwise tell them to open menu
    if text.lower() not in ("/start", "/shop"):
        await msg.reply_text("Type /start to open the menu.")


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

    # errors
    app.add_error_handler(lambda u, c: logger.error(c.error))

    print("🤖 Marketplace Bot running — Ctrl+C to stop")
    app.run_polling()


if __name__ == "__main__":
    main()
