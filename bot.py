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
from telegram.error import BadRequest
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
from modules import storage, ui, chat, seller, notifications  # noqa: E402
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

    # Acknowledge to clear the Telegram spinner
    try:
        await q.answer()
    except Exception:
        pass

    # Helper: send a fresh menu if we just deleted a photo (or editing fails)
    async def send_menu_fresh(tab: str):
        uid = update.effective_user.id
        if tab == "shop":
            txt, kb = ui.build_shop_keyboard()
            return await context.bot.send_message(uid, txt, reply_markup=kb, parse_mode="Markdown")
        if tab == "wallet":
            bal = storage.get_balance(uid)
            pub = wallet.ensure_user_wallet(uid)["public_key"]
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Deposit",  callback_data="wallet:deposit")],
                [InlineKeyboardButton("📤 Withdraw", callback_data="wallet:withdraw")],
                [InlineKeyboardButton("🏠 Menu",     callback_data="menu:main")],
            ])
            return await context.bot.send_message(
                uid, f"💼 *Wallet*\nFiat: ${bal:.2f}\nSolana: `{pub}`\n",
                reply_markup=kb, parse_mode="Markdown"
            )
        if tab == "messages":
            threads = storage.load_json(storage.MESSAGES_FILE)
            btns = [[InlineKeyboardButton(f"💬 {v['product']['name']}", callback_data=f"chat:open:{k}")]
                    for k, v in threads.items() if uid in (v.get("buyer_id"), v.get("seller_id"))]
            btns.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])
            msg = "💌 *Your Chats*:\n" if len(btns) > 1 else "No chats yet."
            return await context.bot.send_message(uid, msg, reply_markup=InlineKeyboardMarkup(btns), parse_mode="Markdown")
        if tab == "sell":
            txt, kb = seller.build_seller_menu(storage.get_role(uid))
            return await context.bot.send_message(uid, txt, reply_markup=kb, parse_mode="Markdown")
        # main / refresh / unknown -> main
        kb, txt = ui.build_main_menu(storage.get_balance(uid))
        return await context.bot.send_message(uid, txt, reply_markup=kb, parse_mode="Markdown")

    try:
        # ---------- MENUS ----------
        if data.startswith("menu:"):
            tab = data.split(":", 1)[1]

            # If this callback came from a photo/caption (e.g., fake PayNow QR),
            # delete it and send a fresh menu instead of trying to edit.
            msg = q.message
            came_from_photo = bool(getattr(msg, "photo", None)) or (msg.caption is not None)

            if came_from_photo:
                try:
                    await msg.delete()
                except Exception:
                    pass
                await send_menu_fresh(tab)
                return

            # Otherwise let the normal menu handler try to edit in place
            try:
                await ui.on_menu(update, context)
                return
            except BadRequest as e:
                # If edit fails (e.g., “no text to edit”), do fresh send fallback
                if "no text" in str(e).lower():
                    await send_menu_fresh(tab)
                    return
                raise

        # ---------- SHOP FLOW ----------
        if data.startswith("buy:"):
            _, sku, qty = data.split(":")
            await ui.on_buy(update, context, sku, int(qty)); return

        if data.startswith("qty:"):
            _, sku, qty = data.split(":")
            await ui.on_qty(update, context, sku, int(qty)); return

        if data.startswith("checkout:"):
            _, sku, qty = data.split(":")
            await ui.on_checkout(update, context, sku, int(qty)); return

        if data.startswith("stripe:"):
            _, sku, qty = data.split(":")
            await ui.create_stripe_checkout(update, context, sku, int(qty)); return

        if data.startswith("paynow:"):
            _, sku, qty = data.split(":")
            await ui.show_paynow(update, context, sku, int(qty)); return

        # Fake gateway returns
        if data.startswith("payconfirm:"):
            order_id = data.split(":", 1)[1]
            from modules.ui import handle_pay_confirm
            await handle_pay_confirm(update, context, order_id); return

        if data.startswith("paycancel:"):
            order_id = data.split(":", 1)[1]
            from modules.ui import handle_pay_cancel
            await handle_pay_cancel(update, context, order_id); return

        if data == "back_to_shop":
            txt, kb = ui.build_shop_keyboard()
            await q.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown"); return

        # ---------- SELLER ----------
        if data.startswith("sell:list"):
            await seller.show_seller_listings(update, context); return

        if data.startswith("sell:remove_confirm:"):
            _, _, sku = data.split(":")
            await seller.confirm_remove_listing(update, context, sku); return

        if data.startswith("sell:remove_do:"):
            _, _, sku = data.split(":")
            await seller.do_remove_listing(update, context, sku); return

        # ---------- CHAT ----------
        if data.startswith("contact:"):
            _, sku, seller_id = data.split(":")
            await chat.on_contact_seller(update, context, sku, int(seller_id)); return

        if data.startswith("chat:open:"):
            _, _, thread_id = data.split(":")
            await chat.on_chat_open(update, context, thread_id); return

        if data == "chat:exit":
            await chat.on_chat_exit(update, context); return

        # ---------- PUBLIC CHAT ----------
        if data == "chat:public_open":
            await chat.on_public_chat_open(update, context); return

        # ---------- WALLET ----------
        if data == "wallet:show_sol":
            await wallet.show_sol_address(update, context); return

        if data == "wallet:withdraw":
            await wallet.start_withdraw_flow(update, context); return

        if data == "wallet:deposit":
            await wallet.show_deposit_info(update, context); return

        # ---------- FUNCTIONS ----------
        if data == "menu:functions":
            await ui.show_functions_menu(update, context); return

        if data == "noop":
            return

        # ---------- ADMIN ----------
        if data == "admin:disputes":
            await ui.admin_open_disputes(update, context); return

        if data.startswith("admin_refund:"):
            _, oid = data.split(":")
            await ui.admin_refund(update, context, oid); return

        if data.startswith("admin_release:"):
            _, oid = data.split(":")
            await ui.admin_release(update, context, oid); return

        logger.info(f"Unhandled callback data: {data}")

    except Exception as e:
        logger.exception("Callback error")
        # Final fallback: if editing fails (e.g., from a photo), DM a fresh error
        try:
            await q.edit_message_text(f"⚠️ Error: {e}\nPlease /start again.")
        except Exception:
            try:
                await context.bot.send_message(update.effective_user.id, f"⚠️ Error: {e}\nPlease /start again.")
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
