# ==========================
# TELEGRAM MARKETPLACE BOT – MODULAR VERSION
# Buyer + Seller + Chat Relay + Public Chat + Solana Wallet
# + Cart, Search, Filter, Fake PayNow
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

    # Deliver any pending notifications (if you use notifications.py)
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
            pass

    # anti-spam
    if storage.is_spamming(user_id):
        return

    # ensure user wallet exists (solana) – safe to fail silently
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

    # ack quickly
    try:
        await q.answer()
    except Exception:
        pass

    try:
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

        if data.startswith("paynow:"):
            _, sku, qty = data.split(":")
            await ui.show_paynow(update, context, sku, int(qty))
            return

        if data == "back_to_shop":
            text, kb = ui.build_shop_keyboard()
            try:
                await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
            except Exception:
                await context.bot.send_message(
                    update.effective_user.id, text, reply_markup=kb, parse_mode="Markdown"
                )
            return

        # ---------- CART ----------
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
                    update.effective_user.id, msg, reply_markup=kb, parse_mode="Markdown"
                )
            return

        if data == "search:ask":
            # put user into search mode
            state = storage.user_flow_state.setdefault(update.effective_user.id, {})
            state["search_mode"] = True
            try:
                await q.edit_message_text(
                    "🔎 *Search mode*\n\nSend me your keywords (e.g. `hoodie`, `cap`, `cat plush`).",
                    parse_mode="Markdown",
                )
            except Exception:
                await context.bot.send_message(
                    update.effective_user.id,
                    "🔎 *Search mode*\n\nSend me your keywords (e.g. `hoodie`, `cap`, `cat plush`).",
                    parse_mode="Markdown",
                )
            return

        if data == "search:clear":
            state = storage.user_flow_state.setdefault(update.effective_user.id, {})
            state.pop("search_mode", None)
            text, kb = ui.build_shop_keyboard()
            try:
                await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
            except Exception:
                await context.bot.send_message(
                    update.effective_user.id, text, reply_markup=kb, parse_mode="Markdown"
                )
            return

        # ---------- FILTER ----------
        if data == "filter:menu":
            txt, kb = ui.build_filter_menu()
            try:
                await q.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
            except Exception:
                await context.bot.send_message(
                    update.effective_user.id, txt, reply_markup=kb, parse_mode="Markdown"
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
                    update.effective_user.id, txt, reply_markup=kb, parse_mode="Markdown"
                )
            return

        # ---------- FAKE GATEWAY RETURN ----------
        if data.startswith("payconfirm:"):
            order_id = data.split(":", 1)[1]
            await ui.handle_pay_confirm(update, context, order_id)
            return

        if data.startswith("paycancel:"):
            order_id = data.split(":", 1)[1]
            await ui.handle_pay_cancel(update, context, order_id)
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

        # (Optional) admin dispute panel – only if you wired it
        if data == "admin:disputes" and hasattr(ui, "admin_open_disputes"):
            await ui.admin_open_disputes(update, context)
            return

        if data.startswith("admin_refund:") and hasattr(ui, "admin_refund"):
            _, oid = data.split(":")
            await ui.admin_refund(update, context, oid)
            return

        if data.startswith("admin_release:") and hasattr(ui, "admin_release"):
            _, oid = data.split(":")
            await ui.admin_release(update, context, oid)
            return

        logger.info(f"Unhandled callback data: {data}")

    except Exception as e:
        logger.exception("Callback error")
        # fallback – send a separate error message so we don't crash on photo/caption edits
        try:
            await q.edit_message_text(f"⚠️ Error: {e}\nPlease /start again.")
        except Exception:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_user.id,
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

    # 4) Wallet withdraw flow
    if wallet.is_in_withdraw_flow(uid):
        await wallet.handle_withdraw_flow(update, context, text)
        return

    # 5) Search mode
    state = storage.user_flow_state.setdefault(uid, {})
    if state.get("search_mode"):
        # clear flag first so only one search per entry
        state.pop("search_mode", None)
        items = ui.search_items(text)
        txt, kb = ui.build_shop_keyboard(filtered_items=items, search_query=text)
        await msg.reply_text(txt, reply_markup=kb, parse_mode="Markdown")
        return

    # 6) Default
    if text.lower() not in ("/start", "/shop"):
        await msg.reply_text("Type /start to open the menu.")


# ==========================
# ERROR HANDLER
# ==========================
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Unhandled error", exc_info=context.error)


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
    app.add_error_handler(on_error)

    print("🤖 Marketplace Bot running — Ctrl+C to stop")
    app.run_polling()


if __name__ == "__main__":
    main()
