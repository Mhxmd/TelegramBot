# ==========================
# TELEGRAM MARKETPLACE BOT – MODULAR VERSION
# Buyer + Seller + Escrow + Solana Wallet + NETS/PayNow/Stripe Sandbox
# ==========================

import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# Load ENV
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Modules
from modules import storage, ui, chat, seller, shopping_cart
import modules.wallet_utils as wallet


# ==========================
# Logging
# ==========================
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
    wallet.ensure_user_wallet(user_id)

    balance = storage.get_balance(user_id)
    kb, text = ui.build_main_menu(balance)

    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")


async def shop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = ui.build_shop_keyboard()
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")


# ==========================
# CALLBACK ROUTER
# ==========================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    data = (q.data or "").strip()

    try: await q.answer()
    except: pass

    try:

        # ========= MENU =========
        if data.startswith("menu:"):
            return await ui.on_menu(update, context)

        # ========= PRODUCT / SHOP =========
        if data == "shop:search":
            return await ui.ask_search(update, context)

        if data.startswith("buy:"):
            _, sku, qty = data.split(":")
            return await ui.on_buy(update, context, sku, int(qty))

        if data.startswith("qty:"):
            _, sku, qty = data.split(":")
            return await ui.on_qty(update, context, sku, int(qty))

        if data.startswith("checkout:"):
            _, sku, qty = data.split(":")
            return await ui.on_checkout(update, context, sku, int(qty))

        if data.startswith("stripe:"):
            _, sku, qty = data.split(":")
            return await ui.create_stripe_checkout(update, context, sku, int(qty))

        if data.startswith("paynow:"):
            _, sku, qty = data.split(":")
            return await ui.show_paynow(update, context, sku, int(qty))

        # NETS for single item
        if data.startswith("nets:"):
            _, sku, qty = data.split(":")
            return await ui.show_nets_qr(update, context, sku, int(qty))

        # ========= CART =========
        if data == "cart:view": return await shopping_cart.view_cart(update, context)
        if data == "cart:checkout_all": return await ui.cart_checkout_all(update, context)
        if data == "cart:cancel": return await shopping_cart.view_cart(update, context)

        if data.startswith("cart_add:"):
            _, sku = data.split(":")
            await shopping_cart.add_item(update, context, sku)
            return await shopping_cart.view_cart(update, context)

        if data.startswith("cart:remove:"):
            _, _, sku = data.split(":")
            return await shopping_cart.remove_item(update, context, sku)

        if data.startswith("cart:addqty:"):
            _, _, sku = data.split(":")
            return await shopping_cart.change_quantity(update, context, sku, +1)

        if data.startswith("cart:subqty:"):
            _, _, sku = data.split(":")
            return await shopping_cart.change_quantity(update, context, sku, -1)

        # CART PAYMENT GATEWAYS
        if data.startswith("stripe_cart:"):
            _, total = data.split(":")
            return await ui.stripe_cart_checkout(update, context, total)

        if data.startswith("paynow_cart:"):
            _, total = data.split(":")
            return await ui.show_paynow_cart(update, context, total)

        if data.startswith("nets_cart:"):
            _, total = data.split(":")
            return await ui.show_nets_cart(update, context, float(total))

        # confirm/cancel escrow payment
        if data.startswith("payconfirm:"):
            return await ui.handle_pay_confirm(update, context, data.split(":", 1)[1])

        if data.startswith("paycancel:"):
            return await ui.handle_pay_cancel(update, context, data.split(":", 1)[1])

        # ========= SELLER =========
        if data.startswith("sell:list"): return await seller.show_seller_listings(update, context)

        if data.startswith("sell:remove_confirm:"):
            return await seller.confirm_remove_listing(update, context, data.split(":")[2])

        if data.startswith("sell:remove_do:"):
            return await seller.do_remove_listing(update, context, data.split(":")[2])

        # ========= CHAT =========
        if data.startswith("contact:"):
            _, sku, seller_id = data.split(":")
            return await chat.on_contact_seller(update, context, sku, int(seller_id))

        if data.startswith("chat:open:"):
            return await chat.on_chat_open(update, context, data.split(":")[2])

        if data == "chat:exit": return await chat.on_chat_exit(update, context)
        if data == "chat:public_open": return await chat.on_public_chat_open(update, context)

        # ========= WALLET =========
        if data == "wallet:deposit": return await wallet.show_deposit_info(update, context)
        if data == "wallet:withdraw": return await wallet.start_withdraw_flow(update, context)

        # ========= ADMIN =========
        if data == "admin:disputes": return await ui.admin_open_disputes(update, context)
        if data.startswith("admin_refund:"): return await ui.admin_refund(update, context, data.split(":")[1])
        if data.startswith("admin_release:"): return await ui.admin_release(update, context, data.split(":")[1])

        logger.info(f"Unhandled callback: {data}")

    except Exception as e:
        logger.exception("Router exception")
        try: await q.edit_message_text(f"⚠️ Error: {e}")
        except: await context.bot.send_message(update.effective_user.id, f"⚠️ Error: {e}")


# ==========================
# MESSAGE HANDLER
# ==========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    uid = msg.from_user.id
    text = (msg.text or "").strip()

    if chat.is_in_public_chat(uid): return await chat.handle_public_message(update, context, text)
    if chat.is_in_private_thread(uid): return await chat.handle_private_message(update, context, text)
    if seller.is_in_seller_flow(uid): return await seller.handle_seller_flow(update, context, text)
    if wallet.is_in_withdraw_flow(uid): return await wallet.handle_withdraw_flow(update, context, text)

    if context.user_data.get("awaiting_search"):
        context.user_data["awaiting_search"] = False
        return await ui.show_search_results(update, context, ui.search_products_by_name(text))

    return await msg.reply_text("Send /start to open the Marketplace.")


# ==========================
# MAIN
# ==========================
def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN missing in .env")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("shop", shop_cmd))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Marketplace Bot running — Ctrl+C to stop")
    app.run_polling()


if __name__ == "__main__":
    main()
