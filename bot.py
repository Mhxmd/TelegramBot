# ==========================
# TELEGRAM MARKETPLACE BOT
# Modular — Shopping Cart + Escrow + Wallet + Chat + Stripe/Nets/PayNow
# ==========================

import os
import logging
from dotenv import load_dotenv
from telegram import Update, LabeledPrice # Added LabeledPrice
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters , PreCheckoutQueryHandler
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
# NATIVE PAYMENT HANDLERS
# ==========================

async def handle_native_payment(update, context):
    query = update.callback_query
    data = query.data.split(":")
    
    # pay_native : provider : amount : (optional sku)
    provider = data[1]
    amount_str = data[2]
    sku = data[3] if len(data) > 3 else "Multiple Items (Cart)"
    
    amount_in_cents = int(float(amount_str) * 100)
    token = PROVIDER_TOKEN_SMART_GLOCAL if provider == "smart_glocal" else PROVIDER_TOKEN_REDSYS
    
    await context.bot.send_invoice(
        chat_id=update.effective_user.id,
        title=f"Purchase: {sku}",
        description=f"Direct payment via {provider.title()}",
        payload=f"PAY-{sku}-{update.effective_user.id}",
        provider_token=token,
        currency="USD",
        prices=[LabeledPrice("Price", amount_in_cents)],
        start_parameter="market-purchase"
    )
    await query.answer()

async def handle_native_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unified handler for both Single Item and Cart checkouts using .env tokens"""
    query = update.callback_query
    data = query.data.split(":")
    
    # Format expected: pay_native:provider:amount:optional_sku
    provider = data[1]
    amount_str = data[2]
    sku = data[3] if len(data) > 3 else "Cart Checkout"
    
    # Pull tokens from Environment
    if provider == "smart_glocal":
        token = os.getenv("PROVIDER_TOKEN_SMART_GLOCAL")
    else:
        token = os.getenv("PROVIDER_TOKEN_REDSYS")

    if not token:
        logger.error(f"Missing provider token for: {provider}")
        return await query.answer("❌ Payment system offline (Token missing).", show_alert=True)

    try:
        price_in_cents = int(float(amount_str) * 100)
        
        await context.bot.send_invoice(
            chat_id=update.effective_user.id,
            title=f"Order: {sku}",
            description=f"Payment via {provider.replace('_', ' ').title()}",
            payload=f"PAY|{uid}|{sku}",
            provider_token=token,
            currency="USD",
            prices=[LabeledPrice("Total", price_in_cents)],
            start_parameter="market-checkout"
        )
        await query.answer()
    except Exception as e:
        logger.error(f"Invoice Generation Error: {e}")
        await query.answer("❌ Failed to create invoice. Try again later.", show_alert=True)

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Final check before the user enters their card details"""
    query = update.pre_checkout_query
    # Check if we have stock one last time here if you want
    if query.invoice_payload != "marketplace-cart-checkout":
        await query.answer(ok=False, error_message="Something went wrong...")
    else:
        await query.answer(ok=True)

async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggered after the money is actually processed"""
    uid = update.effective_user.id
    # Clear the user's cart now that they paid
    shopping_cart.clear_cart(uid)
    
    await update.message.reply_text(
        "✅ **Payment Successful!**\nThank you for your purchase. Your order is now being processed.",
        parse_mode="Markdown"
    )

# ==========================
# CALLBACK ROUTER
# ==========================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    data = (q.data or "").strip()
    # Define user_id so it's available for all logic below
    user_id = update.effective_user.id

    try:
        await q.answer()
    except:
        pass

    try:
        # MENUS
        if data.startswith("menu:"):
            return await ui.on_menu(update, context)
        # Shop Page
        if data.startswith("shop_page:"):
            page = int(data.split(":")[1])
            txt, kb = ui.build_shop_keyboard(uid=user_id, page=page)
            await q.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
        
        # VIEW ITEM DETAILS (Image & Stock)
        if data.startswith("view_item:"):
            sku = data.split(":")[1]
            return await ui.view_item_details(update, context, sku)

        # SELLER TOGGLE HIDE/UNHIDE
        if data.startswith("sell:toggle_hide:"):
            sku = data.split(":")[2]
            # Flip the hidden status in storage
            storage.toggle_product_visibility(sku) 
            # Refresh the seller's listing view
            return await seller.show_seller_listings(update, context)

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

        # Add this inside the "try" block of your callback_router
        if data.startswith("pay_native:"):
            return await handle_native_checkout(update, context)
                
        # PAYMENTS SINGLE ITEM NETS

        if data.startswith("nets:"):
            _, sku, qty = data.split(":")
            return await ui.show_nets_qr(update, context, sku, int(qty))

        # Crypto Functions
        if data == "wallet:deposit":
            return await wallet.show_deposit_info(update, context)

        if data == "wallet:withdraw":
            return await wallet.start_withdraw_flow(update, context)

        if data == "wallet:confirm_withdraw":
            return await wallet.confirm_withdraw(update, context)

        # Order Dispute
        if data.startswith("order_dispute_init:"):
            oid = data.split(":")[1]
            return await ui.file_order_dispute(update, context, oid)

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
        if data.startswith("sell:list"):
            return await seller.show_seller_listings(update, context)

        if data.startswith("sell:remove_confirm"):
            return await seller.confirm_remove_listing(update, context, data.split(":")[2])

        if data.startswith("sell:remove_do"):
            return await seller.do_remove_listing(update, context, data.split(":")[2])

        if data == "sell:add":
            return await seller.start_add_listing(update, context)

        if data == "sell:register":
            return await seller.register_seller(update, context)

        if data.startswith("captcha:"):
            uid = update.effective_user.id
            answer = data.split(":")[1]
            ok = seller.verify_captcha(uid, answer)
            if ok:
                return await ui.on_menu(update, context)
            else:
                return await q.answer("❌ Wrong answer", show_alert=True)

        # CHAT
        if data.startswith("contact:"):
            _, sku, sid = data.split(":")
            return await chat.on_contact_seller(update, context, sku, int(sid))

        if data.startswith("chat:open:"):
            return await chat.on_chat_open(update, context, data.split(":")[1])

        if data.startswith("chat:delete:"):
            thread_id = data.split(":")[2]
            storage.hide_chat_for_user(thread_id, user_id) 
            return await chat.on_chat_delete(update, context, thread_id)
     
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
            oid = data.split(":")[1]
            return await ui.admin_refund(update, context, oid)

        if data.startswith("admin_release:"):
            oid = data.split(":")[1]
            return await ui.admin_release(update, context, oid)
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

    # 1. HANDLE PHOTO UPLOADS (For Seller Image Flow)
    if msg.photo:
        st = storage.user_flow_state.get(uid)
        if st and st.get("phase") == "add_image":
            file_id = msg.photo[-1].file_id
            return await seller.finalize_listing(update, context, image_url=file_id)

    # 2. HANDLE TEXT
    if not text: 
        return

    # 3. SEARCH MODE (Moved up to catch input during active search)
    search_mode = context.user_data.get("awaiting_search")
    if search_mode:
        context.user_data["awaiting_search"] = None # Reset state immediately
        
        if search_mode == "users":
            # Pass all products to help find sellers not yet in the user DB
            all_prods = ui.enumerate_all_products() 
            results = storage.search_users(text, all_prods)
            return await ui.show_user_search_results(update, context, results)
            
        elif search_mode == "products":
            results = ui.search_products_by_name(text)
            logger.info(f"Search query='{text}' results={len(results)}")
            return await ui.show_search_results(update, context, results)


    # 4. CHAT SYSTEMS
    if chat.is_in_public_chat(uid):
        return await chat.handle_public_message(update, context, text)

    if chat.is_in_private_thread(uid):
        return await chat.handle_private_message(update, context, text)

    # 5. SELLER FLOW
    if seller.is_in_seller_flow(uid):
        return await seller.handle_seller_flow(update, context, text)

    # 6. WALLET WITHDRAWAL
    if wallet.is_in_withdraw_flow(uid):
        return await wallet.handle_withdraw_flow(update, context, text)


# ==========================
# MAIN
# ==========================
def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN missing in .env")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Mandatory Payment Logic Handlers (Pre-checkout and Success)
    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_callback))

    # Standard Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("shop", shop_cmd))
    
    # The Router handles all menu clicks (including pay_native)
    app.add_handler(CallbackQueryHandler(callback_router))
    
    # General Message Handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_message))

    print("🤖 Bot running... Tokens loaded from .env")
    app.run_polling()

if __name__ == "__main__":
    main()