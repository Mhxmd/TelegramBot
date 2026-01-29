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
print("RUNNING BOT.PY:", __file__)


# Load .env
load_dotenv()   
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
PROVIDER_TOKEN_SMART_GLOCAL = (os.getenv("PROVIDER_TOKEN_SMART_GLOCAL") or "").strip()
PROVIDER_TOKEN_REDSYS = (os.getenv("PROVIDER_TOKEN_REDSYS") or "").strip()
PROVIDER_TOKEN_STRIPE = (os.getenv("PROVIDER_TOKEN_STRIPE") or "").strip()
SMART_GLOCAL_CURRENCY = (os.getenv("SMART_GLOCAL_CURRENCY") or "SGD").strip().upper()
REDSYS_CURRENCY = (os.getenv("REDSYS_CURRENCY") or "SGD").strip().upper()


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

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("UNHANDLED ERROR", exc_info=context.error)


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

async def create_native_invoice_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE, provider: str, sku: str, qty: int):
    """
    Single-item Smart Glocal / Redsys invoice checkout.
    Callback format expected:
      pay_native:<provider>:<amount>:<sku>:<qty>
    Produces payload:
      PAY|<order_id>|<sku>|<qty>
    """
    query = update.callback_query
    user_id = update.effective_user.id
    qty = int(qty) if qty else 1

    # Pull provider token from .env
    tokens = {
        "smart_glocal": PROVIDER_TOKEN_SMART_GLOCAL,
        "redsys": PROVIDER_TOKEN_REDSYS,
    }
    token = (tokens.get(provider) or "").strip()


    if not token:
        logger.error(f"Missing provider token for: {provider}")
        return await query.edit_message_text(
            "❌ Payment provider token missing in .env",
            parse_mode="Markdown"
        )

    # Get item details from ui catalog (single source of truth)
    item = ui.get_any_product_by_sku(sku)
    if not item:
        return await query.edit_message_text(
            "❌ Item not found.",
            parse_mode="Markdown"
        )


    # Total from item * qty (do not trust callback amount)
    total_val = float(item.get("price", 0)) * int(qty)
    price_in_cents = int(round(total_val * 100))

    # Create order
    order_id = storage.add_order(
        buyer_id=user_id,
        item_name=item.get("name", sku),
        qty=int(qty),
        amount=float(total_val),
        method=provider,
        seller_id=int(item.get("seller_id", 0)),
    )

    # Reserve inventory
    ok, msg = inventory.reserve_for_payment(order_id, sku, int(qty))
    if not ok:
        storage.update_order_status(order_id, "failed", reason=msg)
        return await query.edit_message_text(
            f"❌ {msg}",
            parse_mode="Markdown"
        )


    title = f"Order: {str(item.get('name','item')).lower()}"

    try:
        currency = SMART_GLOCAL_CURRENCY if provider == "smart_glocal" else REDSYS_CURRENCY

        await context.bot.send_invoice(
            chat_id=user_id,
            title=f"Order: {str(sku).lower()}",
            description=f"Checkout via {provider}",
            payload=f"PAY|{order_id}|{sku}|{int(qty)}",
            provider_token=token,
            currency=currency,
            prices=[LabeledPrice("Total Price", price_in_cents)],
            start_parameter="market-single-native",
        )


    except Exception as e:
        logger.exception("send_invoice failed (single native)")
        return await query.edit_message_text(
            f"❌ Invoice failed: {type(e).__name__}: {e}",
            parse_mode="Markdown"
        )

    return 

async def handle_native_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user_id = update.effective_user.id
    data = (q.data or "")
    parts = data.split(":")
    if len(parts) < 4:
        return await q.edit_message_text("❌ Bad checkout payload.", parse_mode="Markdown")

    provider = parts[1].strip()
    ref = parts[3].strip().lower()
    if ref != "cart":
        return await q.edit_message_text("❌ Not a cart checkout.", parse_mode="Markdown")

    tokens = {
        "smart_glocal": PROVIDER_TOKEN_SMART_GLOCAL,
        "redsys": PROVIDER_TOKEN_REDSYS,
    }
    token = (tokens.get(provider) or "").strip()
    if not token:
        return await q.edit_message_text("❌ Missing provider token in .env", parse_mode="Markdown")

    cart = shopping_cart.get_user_cart(user_id)
    if not cart:
        return await q.edit_message_text("🛒 Cart is empty.", parse_mode="Markdown")

    total_val = 0.0
    total_qty = 0
    items = []
    for sku, i in cart.items():
        qty = int(i.get("qty", 1) or 1)
        price = float(i.get("price", 0) or 0)
        total_val += price * qty
        total_qty += qty
        items.append({"sku": sku, "qty": qty})

    currency = SMART_GLOCAL_CURRENCY if provider == "smart_glocal" else REDSYS_CURRENCY

    cart_skus = list(cart.keys())
    title = f"Order: {cart_skus[0].lower()}" if len(cart_skus) == 1 else "Order: cart"

    order_id = storage.add_order(
        buyer_id=user_id,
        item_name="Cart" if len(cart_skus) != 1 else cart.get(cart_skus[0], {}).get("name", cart_skus[0]),
        qty=total_qty,
        amount=float(total_val),
        method=provider,
        seller_id=0
    )

    ok, msg = inventory.reserve_cart_for_payment(order_id, items)
    if not ok:
        storage.update_order_status(order_id, "failed", reason=msg)
        return await q.edit_message_text(f"❌ {msg}", parse_mode="Markdown")

    price_in_cents = int(round(total_val * 100))

    try:
        await context.bot.send_invoice(
            chat_id=user_id,
            title=title,
            description=f"Checkout via {provider}",
            payload=f"PAYCART|{order_id}",
            provider_token=token,
            currency=currency,
            prices=[LabeledPrice("Total", price_in_cents)],
            start_parameter="market-cart-native"
        )
        # optional: update UI (NOT q.answer)
        return await q.edit_message_text("✅ Invoice sent. Check the payment message.", parse_mode="Markdown")

    except Exception as e:
        logger.exception("CART send_invoice failed")
        storage.update_order_status(order_id, "failed", reason=str(e))
        return await q.edit_message_text(f"❌ Invoice failed: {type(e).__name__}: {e}", parse_mode="Markdown")

async def handle_native_checkout_direct(update: Update, context: ContextTypes.DEFAULT_TYPE, provider: str):
    q = update.callback_query
    user_id = update.effective_user.id

    provider = (provider or "").strip().lower()
    if provider not in ("smart_glocal", "redsys"):
        return await q.edit_message_text("❌ Unsupported provider.", parse_mode="Markdown")

    token = PROVIDER_TOKEN_SMART_GLOCAL if provider == "smart_glocal" else PROVIDER_TOKEN_REDSYS
    token = (token or "").strip()
    if not token:
        return await q.edit_message_text("❌ Missing provider token in .env", parse_mode="Markdown")

    cart = shopping_cart.get_user_cart(user_id)
    if not cart:
        return await q.edit_message_text("🛒 Cart is empty.", parse_mode="Markdown")

    total_val = 0.0
    total_qty = 0
    items = []
    for sku, i in cart.items():
        qty = int(i.get("qty", 1) or 1)
        price = float(i.get("price", 0) or 0)
        total_val += price * qty
        total_qty += qty
        items.append({"sku": sku, "qty": qty})

    currency = SMART_GLOCAL_CURRENCY if provider == "smart_glocal" else REDSYS_CURRENCY

    cart_skus = list(cart.keys())
    title = f"Order: {cart_skus[0].lower()}" if len(cart_skus) == 1 else "Order: cart"

    order_id = storage.add_order(
        buyer_id=user_id,
        item_name="Cart" if len(cart_skus) != 1 else cart.get(cart_skus[0], {}).get("name", cart_skus[0]),
        qty=total_qty,
        amount=float(total_val),
        method=provider,
        seller_id=0
    )

    ok, msg = inventory.reserve_cart_for_payment(order_id, items)
    if not ok:
        storage.update_order_status(order_id, "failed", reason=msg)
        return await q.edit_message_text(f"❌ {msg}", parse_mode="Markdown")

    price_in_cents = int(round(total_val * 100))

    try:
        await context.bot.send_invoice(
            chat_id=user_id,
            title=title,
            description=f"Checkout via {provider}",
            payload=f"PAYCART|{order_id}",
            provider_token=token,
            currency=currency,
            prices=[LabeledPrice("Total", price_in_cents)],
            start_parameter="market-cart-native",
        )
        return await q.edit_message_text("✅ Invoice sent. Check the payment message.", parse_mode="Markdown")

    except Exception as e:
        logger.exception("CART send_invoice failed")
        storage.update_order_status(order_id, "failed", reason=str(e))
        return await q.edit_message_text(f"❌ Invoice failed: {type(e).__name__}: {e}", parse_mode="Markdown")
        
async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = msg.from_user.id
    payload = msg.successful_payment.invoice_payload

    # Expected payload formats:
    # PAY|order_id|sku|qty
    # PAYCART|order_id
    parts = payload.split("|")

    if parts[0] == "PAY":
        order_id = parts[1]
    elif parts[0] == "PAYCART":
        order_id = parts[1]
    else:
        return await msg.reply_text("⚠️ Unknown payment payload.")

    ok, err = inventory.confirm_payment(order_id)
    if not ok:
        return await msg.reply_text(f"⚠️ Payment received but inventory failed: {err}")

    storage.update_order_status(order_id, "escrow_hold")
    shopping_cart.clear_cart(uid)

    await msg.reply_text(
        "✅ Payment successful.\nOrder is now held in escrow.",
        parse_mode="Markdown"
    )

async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    payload = (query.invoice_payload or "").strip()

    if not payload.startswith(("PAY|", "PAYCART|")):
        return await query.answer(ok=False, error_message="Invalid order payload")

    return await query.answer(ok=True)


# ==========================
# CALLBACK ROUTER
# ==========================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):

    q = update.callback_query
    data = (q.data or "").strip()
    # Define user_id so it's available for all logic below
    user_id = update.effective_user.id

    # DEBUG: prove every button click hits the router
    print("CALLBACK:", data)

    # ACK EVERY CALLBACK ASAP (only once)
    try:
        await q.answer()
    except:
        pass


    # Only answer for noop. For everything else, let the specific handler answer.
    if data == "noop":
        return

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
            return await ui.on_menu(update, context)
        
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
            return await ui.on_menu(update, context)

        if data == "orderunarchiveall":
            uid = update.effective_user.id
            n = storage.unarchive_all_for_user(uid)
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
                return await q.edit_message_text(f"Not enough stock. {stock} left.", parse_mode="Markdown")
            return await ui.on_buy(update, context, sku, qty)

        if data.startswith("qty:"):
            _, sku, qty = data.split(":")
            return await ui.on_qty(update, context, sku, int(qty))

        if data.startswith("checkout:"):
            _, sku, qty = data.split(":")
            return await ui.on_checkout(update, context, sku, int(qty))

        # CART NATIVE (Smart Glocal / Redsys) — supports pay_native_cart:<provider>:<total>
        if data.startswith("pay_native_cart:"):
            await q.edit_message_text(f"DEBUG: hit pay_native_cart -> {data}", parse_mode="Markdown")
            parts = data.split(":")
            if len(parts) != 3:
                return await q.edit_message_text("❌ Invalid cart payment payload.", parse_mode="Markdown")

            provider = parts[1].strip()
            total = parts[2].strip()  # not trusted, but keep for logs

            # Call your existing cart native handler by reusing the same logic,
            # but without relying on the callback format.
            return await handle_native_checkout_direct(update, context, provider)

        # PAYMENTS (Stripe / Smart Glocal / Redsys) + Cart support
        if data.startswith("pay_native:"):
            parts = data.split(":")

            # Always ACK already handled globally

            provider = parts[1]

            # CART FLOW
            if len(parts) == 4 and parts[3] == "cart":
                return await handle_native_checkout(update, context)

            # SINGLE ITEM FLOW
            if len(parts) != 5:
                return await q.edit_message_text(
                    "❌ Invalid payment payload.",
                parse_mode="Markdown"
            )

            total = parts[2]   # ignored on purpose
            sku = parts[3]
            qty = int(parts[4])

            if provider == "stripe":
                return await ui.create_stripe_checkout(update, context, sku, qty)

            if provider in ("smart_glocal", "redsys"):
                return await create_native_invoice_checkout(
                update, context, provider, sku, qty
            )

            return await q.edit_message_text(
                f"❌ Unknown provider: {provider}",
                parse_mode="Markdown"
            )

        
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
            await shopping_cart.add_item(update, context, sku)
            return await shopping_cart.show_add_to_cart_feedback(update, context, sku, source=source)

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

        if data.startswith("cart:edit:"):
            _, _, sku, source = data.split(":")
            return await shopping_cart.show_add_to_cart_feedback(update, context, sku, source=source)

        # --- SOLANA CRYPTO CHECKOUT ---
        if data.startswith("pay_crypto:solana:"):
            parts = data.split(":")
            # pay_crypto:solana:<usd>:Cart OR pay_crypto:solana:<usd>:<sku>
            usd_amount = parts[2]
            ref = parts[3] if len(parts) > 3 else ""

            usd_val = float(usd_amount)

            sol_price = 100.0  # replace with real rates later
            sol_needed = usd_val / sol_price

            user_wallet = wallet.ensure_user_wallet(user_id)
            balance = wallet.get_balance_devnet(user_wallet["public_key"])

            if balance < sol_needed:
                return await q.edit_message_text(
                    f"❌ Insufficient SOL. Need {sol_needed:.4f}, have {balance:.4f}",
                    parse_mode="Markdown"
                )

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm SOL Payment", callback_data=f"confirm_crypto_pay:{sol_needed}:{usd_val}:{ref}")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cart:view" if ref == "Cart" else "menu:shop")]
            ])

            return await q.edit_message_text(
                f"💎 *Solana Checkout*\n\n"
                f"Total USD: *${usd_val:.2f}*\n"
                f"Estimated SOL: *{sol_needed:.4f} SOL*\n\n"
                f"Confirm payment from your bot wallet?",
                parse_mode="Markdown",
                reply_markup=kb
            )


        # --- CRYPTO EXECUTION ---
        if data.startswith("confirm_crypto_pay:"):
            parts = data.split(":")
            sol_amt = parts[1]
            usd_amt = parts[2]
            ref = parts[3] if len(parts) > 3 else ""

            ESCROW_WALLET = "YOUR_SYSTEM_SOLANA_WALLET_ADDRESS"

            user_wallet = wallet.ensure_user_wallet(user_id)
            result = wallet.send_sol(user_wallet["private_key"], ESCROW_WALLET, float(sol_amt))

            if isinstance(result, dict) and "error" in result:
                return await q.edit_message_text(f"❌ Crypto Error: {result['error']}")

            if ref == "Cart":
                shopping_cart.clear_cart(user_id)

            storage.add_order(user_id, "Cart Purchase (Crypto)", 1, float(usd_amt), "Solana", 1)

        return await q.edit_message_text(
            f"✅ *Payment Successful!*\n\nTransaction ID:\n`{result}`",
            parse_mode="Markdown"
        )


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
                return await q.edit_message_text("❌ Wrong answer", parse_mode="Markdown")

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

        if data.startswith("chat:order:"):
            oid = data.split(":")[2]
            return await chat.on_chat_from_order(update, context, oid)

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
    app.add_error_handler(error_handler)
    app.run_polling()



if __name__ == "__main__":
    main()