# ==========================
# TELEGRAM MARKETPLACE BOT
# Modular — Shopping Cart + Escrow + Wallet + Chat + Stripe/Nets/PayNow
# ==========================

import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# Load .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Modules
from modules import storage, ui, chat, seller, shopping_cart, inventory
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
# START COMMAND
# ==========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    storage.ensure_user_exists(user_id, update.effective_user.username)
    wallet.ensure_user_wallet(user_id)

    balance = storage.get_balance(user_id)
    
    #UPDATED: pass user_id into build_main_menu()
    kb, text = ui.build_main_menu(balance, user_id)

    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")


# ==========================
# SHOP COMMAND
# ==========================
async def shop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt, kb = ui.build_shop_keyboard(uid)
    await update.message.reply_text(txt, reply_markup=kb, parse_mode="Markdown")


# ==========================
# CALLBACK ROUTER
# ==========================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    data = (q.data or "").strip()

    try:
        await q.answer()
    except:
        pass

    try:
        # MENUS
        if data.startswith("menu:"):
            return await ui.on_menu(update, context)
        
        # ORDER CANCEL (pending)
        if data.startswith("ordercancel:"):
            _, oid = data.split(":", 1)
            uid = update.effective_user.id

            ok, msg = storage.cancel_pending_order(oid, uid, grace_seconds=900)
            await q.answer(msg, show_alert=not ok)

            # refresh Orders list by editing the same message
            try:
                await ui.on_menu(update, context)  # works because callback_data is still menu:orders in that message
            except:
                pass

            # safest: force refresh by editing message to Orders screen directly
            # (re-render orders screen using the same callback query)
            q2 = update.callback_query
            q2_data_backup = q2.data
            try:
                q2._data = "menu:orders"  # do NOT do this
            except:
                pass

            # clean solution: call Orders renderer logic directly
            # easiest approach: reuse ui.on_menu by calling a small helper instead (recommended below)

            return await ui.on_menu(update, context)
        
        # ORDER ARCHIVE (per user)
        if data.startswith("orderarchive:"):
            _, oid = data.split(":", 1)
            uid = update.effective_user.id
            ok, msg = storage.archive_order_for_user(oid, uid)
            await q.answer(msg, show_alert=not ok)
            return await ui.on_menu(update, context)

        if data == "orderunarchiveall":
            uid = update.effective_user.id
            n = storage.unarchive_all_for_user(uid)
            await q.answer(f"Restored {n} order(s).", show_alert=False)
            return await ui.on_menu(update, context)

        # SEARCH
        if data == "shop:search":
            return await ui.ask_search(update, context)
        
        if data == "search:users":
         return await ui.ask_user_search(update, context)

        # BUY FLOW
        if data.startswith("buy:"):
            _, sku, qty = data.split(":")
            qty = int(qty)
            ok, stock = inventory.check_stock(sku, qty)
            if not ok:
                return await q.answer(f"Not enough stock. {stock} left.", show_alert=True)
            return await ui.on_buy(update, context, sku, qty)

        if data.startswith("qty:"):
            _, sku, qty = data.split(":")
            return await ui.on_qty(update, context, sku, int(qty))

        if data.startswith("checkout:"):
            _, sku, qty = data.split(":")
            return await ui.on_checkout(update, context, sku, int(qty))

        # PAYMENTS SINGLE ITEM
        if data.startswith("stripe:"):
            _, sku, qty = data.split(":")
            return await ui.create_stripe_checkout(update, context, sku, int(qty))

        if data.startswith("hitpay:"):
            _, sku, qty = data.split(":")
            return await ui.create_hitpay_checkout(update, context, sku, int(qty))
        
        # HitPay Checkout - Cart

        if data.startswith("hitpay_cart:"):
            _, total = data.split(":")
            return await ui.create_hitpay_cart_checkout(update, context, float(total))

        # PAYMENTS SINGLE ITEM NETS

        if data.startswith("nets:"):
            _, sku, qty = data.split(":")
            return await ui.show_nets_qr(update, context, sku, int(qty))

        # ==========================
        # CRYPTO PAYMENTS (SOL)
        # ==========================

        if data.startswith("crypto:"):
            _, sku, qty = data.split(":")
            return await ui.crypto_checkout(update, context, sku, int(qty))

        if data.startswith("crypto_confirm:"):
            _, sku, qty = data.split(":")
            return await ui.crypto_confirm(update, context, sku, int(qty))


        # Crypto Functions
        if data == "wallet:deposit":
            return await wallet.show_deposit_info(update, context)

        if data == "wallet:withdraw":
            return await wallet.start_withdraw_flow(update, context)

        if data == "wallet:confirm_withdraw":
            return await wallet.confirm_withdraw(update, context)

        # ==========================
        # CART SYSTEM
        # ==========================

        if data == "cart:view":
            return await shopping_cart.view_cart(update, context)

        if data.startswith("cart:add:"):
            _, _, sku = data.split(":")
            await shopping_cart.add_item(update, context, sku)
            return await shopping_cart.show_add_to_cart_feedback(update, context, sku)

        if data.startswith("cart:subqty:"):
            _, _, sku = data.split(":")
            return await shopping_cart.change_quantity(update, context, sku, -1)

        if data.startswith("cart:addqty:"):
            _, _, sku = data.split(":")
            return await shopping_cart.change_quantity(update, context, sku, +1)

        if data.startswith("cart:remove:"):
            _, _, sku = data.split(":")
            return await shopping_cart.remove_item(update, context, sku)
        
        if data == "cart:clear_all":
            return await shopping_cart.clear_all(update, context)


        if data == "cart:checkout_all":
            return await ui.cart_checkout_all(update, context)

        # CRYPTO CART CHECKOUT
        if data.startswith("crypto_cart:"):
            _, total = data.split(":")
            return await ui.crypto_cart_checkout(update, context, float(total))

        #Crypto Payment Confirmation - Cart
        if data.startswith("crypto_confirm:"):
            _, total = data.split(":")
            uid = update.effective_user.id

            shopping_cart.clear_cart(uid)

            return await q.edit_message_text(
                "✅ *Crypto payment marked as sent!*\n\n"
                "🔒 Funds are now in escrow.\n"
                "📦 Seller will be notified.\n"
                "🛡 Admin releases funds after confirmation.",
                parse_mode="Markdown",
            )


        if data.startswith("stripe_cart:"):
            _, total = data.split(":")
            return await ui.stripe_cart_checkout(update, context, total)

        if data.startswith("paynow_cart:"):
            _, total = data.split(":")
            return await ui.show_paynow_cart(update, context, total)

        if data.startswith("nets_cart:"):
            _, total = data.split(":")
            return await ui.show_nets_cart(update, context, float(total))

        if data == "cart:confirm_payment":
            await shopping_cart.clear_cart(update.effective_user.id)
            return await q.edit_message_text("✅ Cart payment confirmed!")

        # ESCROW SYSTEM
        if data.startswith("payconfirm:"):
            return await ui.handle_pay_confirm(update, context, data.split(":",1)[1])

        if data.startswith("paycancel:"):
            return await ui.handle_pay_cancel(update, context, data.split(":",1)[1])

    
        # SELLER
        if data == "sell:add":
            return await seller.start_add_listing(update, context)

        if data == "sell:list":
            return await seller.show_seller_listings(update, context)

        if data.startswith("sell:remove_confirm"):
            return await seller.confirm_remove_listing(update, context, data.split(":")[2])

        if data.startswith("sell:remove_do"):
            return await seller.do_remove_listing(update, context, data.split(":")[2])

        if data == "sell:register":
            return await seller.register_seller(update, context)

        if data == "sell:cancel":
            storage.user_flow_state.pop(update.effective_user.id, None)
            text, kb = seller.build_seller_menu(storage.get_role(update.effective_user.id))
            return await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

        # CHAT
        if data.startswith("contact:"):
            _, sku, sid = data.split(":")
            return await chat.on_contact_seller(update, context, sku, int(sid))

        if data.startswith("chat:open:"):
            return await chat.on_chat_open(update, context, data.split(":")[1])

        if data == "chat:exit":
            return await chat.on_chat_exit(update, context)

        if data == "chat:public_open":
            return await chat.on_public_chat_open(update, context)
        
        if data.startswith("chat:user:"):
         target_id = int(data.split(":")[2])
         return await chat.on_chat_user(update, context, target_id)

        # WALLET
        if data == "wallet:deposit":
            return await wallet.show_deposit_info(update, context)

        if data == "wallet:withdraw":
            return await wallet.start_withdraw_flow(update, context)

        # ADMIN
        if data == "admin:disputes":
            return await ui.admin_open_disputes(update, context)

        if data.startswith("admin_refund:"):
            return await ui.admin_refund(update, context, data.split(":")[1])

        if data.startswith("admin_release:"):
            return await ui.admin_release(update, context, data.split(":")[1])

    except Exception as e:
        logger.exception("Callback router error")
        try:
            await q.edit_message_text(f"⚠️ Error: {e}")
        except:
            await context.bot.send_message(update.effective_user.id, f"⚠️ Error: {e}")


# ==========================
# MESSAGE ROUTER
# ==========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    uid = msg.from_user.id
    text = (msg.text or "").strip()
    storage.ensure_user_exists(uid, update.effective_user.username)


    # CHAT systems
    if chat.is_in_public_chat(uid):
        return await chat.handle_public_message(update, context, text)

    if chat.is_in_private_thread(uid):
        return await chat.handle_private_message(update, context, text)

    # SELLER
    if seller.is_in_seller_flow(uid):
        return await seller.handle_seller_flow(update, context, text)

    # WALLET WITHDRAWAL
    if wallet.is_in_withdraw_flow(uid):
        return await wallet.handle_withdraw_flow(update, context, text)

    mode = context.user_data.get("awaiting_search")

    if mode == "users":
        context.user_data["awaiting_search"] = None
        results = storage.search_users(text)
        return await ui.show_user_search_results(update, context, results)

    if mode == "products":
        context.user_data["awaiting_search"] = None
        results = ui.search_products_by_name(text)
        return await ui.show_search_results(update, context, results)

    mode = context.user_data.get("awaiting_search")

    if mode == "products":
        context.user_data["awaiting_search"] = None
        results = ui.search_products_by_name(text)
        return await ui.show_search_results(update, context, results)

    if mode == "users":
        context.user_data["awaiting_search"] = None
        results = storage.search_users(text)   # YOU MUST HAVE THIS
        return await ui.show_user_search_results(update, context, results)


    results = ui.search_products_by_name(text)
    return await ui.show_search_results(update, context, results)

    


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

    print("🤖 Bot running... Ctrl+C to stop")
    app.run_polling()


if __name__ == "__main__":
    main()
