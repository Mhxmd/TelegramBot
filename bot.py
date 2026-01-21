# ==========================
# TELEGRAM MARKETPLACE BOT
# Modular — Shopping Cart + Escrow + Wallet + Chat + Stripe/Nets/PayNow
# ==========================

import os
import logging
from dotenv import load_dotenv
from telegram import Update, LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters , PreCheckoutQueryHandler
)

# Load .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Modules
# ==========================
# MODULES IMPORT
# ==========================
from modules import storage, ui, chat, seller, shopping_cart, inventory
from modules import wallet_utils as wallet  # <--- MUST HAVE "as wallet"

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
def _load_orders():
    return storage.load_json(storage.ORDERS_FILE)

def _save_orders(d):
    storage.save_json(storage.ORDERS_FILE, d)

def _patch_order_meta(order_id: str, patch: dict):
    orders = _load_orders()
    if order_id not in orders:
        return False
    orders[order_id].update(patch)
    _save_orders(orders)
    return True

async def handle_stripe_cart_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE, total_str: str):
    """
    Creates:
    - 1 cart order (parent) with item_name="Cart"
    - many item orders (child), 1 per SKU in cart
    Reserves inventory for each child order.
    Sends 1 Telegram invoice with payload PAYCART|<cart_order_id>
    """
    query = update.callback_query
    user_id = update.effective_user.id

    # Provider token for Telegram Payments (Stripe)
    token = os.getenv("PROVIDER_TOKEN_STRIPE")
    if not token:
        return await query.answer("❌ Stripe provider token missing in .env", show_alert=True)

    cart = shopping_cart.get_cart(user_id)  # {sku: {qty, price, name, ...}}
    if not cart:
        return await query.answer("❌ Your cart is empty.", show_alert=True)

    try:
        total = float(total_str)
    except:
        return await query.answer("❌ Invalid cart total.", show_alert=True)

    # Create parent cart order
    cart_order_id = storage.add_order(
        buyer_id=user_id,
        item_name="Cart",
        qty=sum(int(it.get("qty", 1)) for it in cart.values()),
        amount=float(total),
        method="stripe_cart",
        seller_id=0
    )

    child_order_ids = []
    reserved_child_ids = []

    # Create child orders + reserve each item
    try:
        for sku, item in cart.items():
            qty = int(item.get("qty", 1))
            price = float(item.get("price", 0.0))
            amount = price * qty

            seller_id = 0
            sid, prod = storage.get_seller_product_by_sku(sku)
            if prod:
                seller_id = int(prod.get("seller_id", 0))

            child_id = storage.add_order(
                buyer_id=user_id,
                item_name=str(sku),
                qty=qty,
                amount=float(amount),
                method="stripe_cart_item",
                seller_id=seller_id
            )
            child_order_ids.append(child_id)

            ok, msg = inventory.reserve_for_payment(child_id, str(sku), qty)
            if not ok:
                storage.update_order_status(child_id, "failed", reason=msg)
                raise RuntimeError(f"{sku}: {msg}")

            reserved_child_ids.append(child_id)

        # Attach children to parent cart order
        _patch_order_meta(cart_order_id, {"cart_child_orders": child_order_ids})

        price_in_cents = int(round(total * 100))

        await context.bot.send_invoice(
            chat_id=user_id,
            title="Order: Cart",
            description="Cart checkout via Stripe",
            payload=f"PAYCART|{cart_order_id}",
            provider_token=token,
            currency="SGD",
            prices=[LabeledPrice("Total Price", price_in_cents)],
            start_parameter="market-cart-checkout"
        )
        await query.answer()

    except Exception as e:
        # Roll back reservations if anything fails
        for oid in reversed(reserved_child_ids):
            try:
                inventory.release_on_failure_or_refund(oid, reason="cart_checkout_failed")
            except:
                pass

        storage.update_order_status(cart_order_id, "failed", reason=str(e))
        return await query.answer(f"❌ Cart checkout failed: {e}", show_alert=True)

async def handle_native_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Single-item Telegram invoice checkout (Stripe / Nets / Smart Glocal)"""
    query = update.callback_query
    data = query.data.split(":")

    # Expected format: pay_native:provider:amount:sku
    provider = data[1]
    amount_str = data[2]
    sku = data[3] if len(data) > 3 else "Product"
    user_id = update.effective_user.id

    if str(sku).strip().lower() == "cart":
        return await query.answer("Use cart checkout buttons.", show_alert=True)

    tokens = {
        "smart_glocal": os.getenv("PROVIDER_TOKEN_SMART_GLOCAL"),
        "redsys": os.getenv("PROVIDER_TOKEN_REDSYS"),
        "stripe": os.getenv("PROVIDER_TOKEN_STRIPE")
    }

    token = tokens.get(provider)
    if not token:
        return await query.answer("❌ Payment provider not configured.", show_alert=True)

    try:
        amount = float(amount_str)
        price_in_cents = int(round(amount * 100))

        seller_id = 0
        sid, prod = storage.get_seller_product_by_sku(sku)
        if prod:
            seller_id = int(prod.get("seller_id", 0))

        order_id = storage.add_order(
            buyer_id=user_id,
            item_name=sku,
            qty=1,
            amount=amount,
            method=provider,
            seller_id=seller_id
        )

        ok, msg = inventory.reserve_for_payment(order_id, sku, 1)
        if not ok:
            storage.update_order_status(order_id, "failed", reason=msg)
            return await query.answer(f"❌ {msg}", show_alert=True)

        await context.bot.send_invoice(
            chat_id=user_id,
            title=f"Order: {sku}",
            description=f"Checkout via {provider}",
            payload=f"PAY|{order_id}|{sku}|1",
            provider_token=token,
            currency="SGD",
            prices=[LabeledPrice("Total Price", price_in_cents)],
            start_parameter="market-checkout"
        )
        await query.answer()

    except Exception as e:
        logger.error(f"Invoice error: {e}")
        await query.answer("❌ Failed to create invoice.", show_alert=True)

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Final check before the user enters card details. Must return ok=True to proceed."""
    query = update.pre_checkout_query
    
    # Validate that the payload matches our generated invoices
    if query.invoice_payload.startswith("PAY"):
        await query.answer(ok=True)
    else:
        logger.warning(f"PreCheckout Rejected: Invalid payload {query.invoice_payload}")
        await query.answer(ok=False, error_message="Order validation failed. Please try again")
        
async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    sp = update.message.successful_payment
    payload = (sp.invoice_payload or "").strip()

    if payload.startswith("PAY|"):
        parts = payload.split("|")
        if len(parts) >= 4 and str(parts[1]).startswith("ord_"):
            order_id = parts[1]

            ok, msg = inventory.confirm_payment(order_id)
            if ok:
                storage.update_order_status(order_id, "escrow_hold")
            else:
                inventory.release_on_failure_or_refund(order_id, reason=f"confirm_failed:{msg}")
                storage.update_order_status(order_id, "failed", reason=msg)

    elif payload.startswith("PAYCART|"):
        parts = payload.split("|")
        if len(parts) >= 2 and str(parts[1]).startswith("ord_"):
            cart_order_id = parts[1]

            orders = _load_orders()
            cart_order = orders.get(cart_order_id, {})
            child_ids = cart_order.get("cart_child_orders", []) or []

            for oid in child_ids:
                ok, msg = inventory.confirm_payment(oid)
                if ok:
                    storage.update_order_status(oid, "escrow_hold")
                else:
                    inventory.release_on_failure_or_refund(oid, reason=f"confirm_failed:{msg}")
                    storage.update_order_status(oid, "failed", reason=msg)

            storage.update_order_status(cart_order_id, "escrow_hold")
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
            return await q.edit_message_text(
                txt,
                reply_markup=kb,
                parse_mode="Markdown"
            )
        
                # ----- ANALYTICS -----
        if data.startswith("analytics:"):
            days = int(data.split(":")[1])
            return await seller.show_analytics(update, context, days)
        
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
        # Inside bot.py -> callback_router
        if data.startswith("pay_native:"):
            return await handle_native_checkout(update, context)

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
            parts = data.split(":")
            sku = parts[2]
            source = parts[3] if len(parts) > 3 else "shop"
            context.user_data["mini_source"] = source
            await shopping_cart.add_item(update, context, sku)
            return await shopping_cart.show_add_to_cart_feedback(update, context, sku, source)

        if data.startswith("cart:remove:"):
            sku = data.split(":")[2]
            shopping_cart.remove_from_cart(user_id, sku)
            return await shopping_cart.view_cart(update, context)
        
        if data.startswith("cart:subqty:"):
            _, _, sku = data.split(":")
            return await shopping_cart.change_quantity(update, context, sku, -1)

        if data.startswith("cart:addqty:"):
            _, _, sku = data.split(":")
            return await shopping_cart.change_quantity(update, context, sku, +1)
        
        # EDIT ITEM → OPEN MINI PANEL
        if data.startswith("cart:edit:"):
            parts = data.split(":")
            sku = parts[2]
            source = parts[3] if len(parts) > 3 else "cart"
            context.user_data["mini_source"] = source
            return await shopping_cart.show_add_to_cart_feedback(update, context, sku, source)

 
        if data == "cart:clear_all":
            return await shopping_cart.clear_all(update, context)
       
        if data == "cart:checkout_all":
            return await ui.cart_checkout_all(update, context)

        if data.startswith("stripe_cart:"):
            _, total = data.split(":")
            return await handle_stripe_cart_checkout(update, context, total)

        if data.startswith("paynow_cart:"):
            _, total = data.split(":")
            return await ui.show_paynow_cart(update, context, total)

# --- SOLANA CRYPTO CHECKOUT (PHASE 1: REVIEW) ---
        if data.startswith("pay_crypto:solana:"):
            parts = data.split(":")
            # parts[2] is USD, parts[3] is SKU
            usd_val = float(parts[2])
            target_sku = parts[3] if len(parts) > 3 else "Cart"
            
            sol_price = 150.0  # rate
            sol_needed = usd_val / sol_price
            
            user_wallet = wallet.ensure_user_wallet(user_id) 
            balance = wallet.get_balance_devnet(user_wallet["public_key"])
            
            if balance < sol_needed:
                return await q.answer(f"❌ Insufficient SOL. Need {sol_needed:.4f}", show_alert=True)

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm SOL Payment", 
                    callback_data=f"confirm_crypto_pay:solana:{usd_val}:{target_sku}")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cart:view")]
            ])
            
            return await q.edit_message_text(
                f"💎 *Solana Checkout*\n\n"
                f"Item: `{target_sku}`\n"
                f"Total: *${usd_val:.2f}* ({sol_needed:.4f} SOL)\n\n"
                "Confirm payment from your bot wallet?",
                parse_mode="Markdown",
                reply_markup=kb
            )
            
        # --- CRYPTO EXECUTION (PHASE 2: SENDING) ---
        if data.startswith("confirm_crypto_pay:"):
            parts = data.split(":")
            # parts[2] is amount, parts[3] is target_sku
            usd_amt = float(parts[2])
            target_sku = parts[3] if len(parts) > 3 else "Cart"
            
            if target_sku == "Cart":
                cart_items = shopping_cart.get_cart(user_id)
                if not cart_items:
                    return await q.edit_message_text("❌ Your cart is empty.")
                first_item_sku = list(cart_items.keys())[0]
            else:
                first_item_sku = target_sku

            # 2. Identify the seller
            seller_id_str, product_data = storage.get_seller_product_by_sku(first_item_sku)

            if not product_data:
                return await q.edit_message_text(f"❌ Product data for {first_item_sku} missing.")

            seller_id = product_data.get("seller_id")
            seller_wallet = wallet.ensure_user_wallet(seller_id)
            dest_addr = seller_wallet["public_key"] 
            
            # 3. Perform Transfer
            sol_amt = usd_amt / 150.0 
            user_wallet = wallet.ensure_user_wallet(user_id)
            result = wallet.send_sol(user_wallet["private_key"], dest_addr, float(sol_amt))
            
            if isinstance(result, dict) and "error" in result:
                return await q.edit_message_text(f"❌ Transaction Failed: {result['error']}")
            
            # Cleanup
            if target_sku == "Cart":
                shopping_cart.clear_cart(user_id)
            
            storage.add_order(user_id, f"Direct: {first_item_sku}", 1, usd_amt, "Solana", seller_id)
            
            kb_back = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="menu:main")]])
            return await q.edit_message_text(f"✅ *Payment Sent!*\n\nID: `{result}`", 
                                     parse_mode="Markdown", reply_markup=kb_back)

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
            return await seller.handle_seller_flow(update, context, text=None)   # photo branch
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
    
    storage.seed_builtin_products_once()

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