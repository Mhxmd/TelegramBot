import os
import qrcode
import re
from io import BytesIO
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, LabeledPrice
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from typing import Optional
from modules import shopping_cart, storage, inventory, wallet_utils, seller
import stripe
import logging
logger = logging.getLogger(__name__)

from modules import storage, seller, chat, inventory, shopping_cart
import modules.wallet_utils as wallet

# Load .env
load_dotenv()
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
stripe.api_key = STRIPE_SECRET_KEY
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# ===========================
# BUILT-IN PRODUCTS (Static)
# ===========================
CATALOG = {
    "cat": {
        "name": "Cat Plush", 
        "price": 15, 
        "emoji": "🐱", 
        "seller_id": 0, 
        "desc": "Cute cat plush.",
        "is_static": True,    # Flag to identify hardcoded items
        "stock": 999          # Ensure they aren't "Out of Stock"
    },
    "hoodie": {
        "name": "Hoodie", 
        "price": 30, 
        "emoji": "🧥", 
        "seller_id": 0, 
        "desc": "Minimalist navy hoodie.",
        "is_static": True,
        "stock": 999
    },
    "blackcap": {
        "name": "Black Cap", 
        "price": 12, 
        "emoji": "🧢", 
        "seller_id": 0, 
        "desc": "Matte black cap.",
        "is_static": True,
        "stock": 999
    },
}

# ==========================================
# PRODUCT LOADING
# ==========================================
def enumerate_all_products():
    items = []
    seen_skus = set()

    # 1. Load dynamic seller products first
    data = storage.load_json(storage.SELLER_PRODUCTS_FILE)
    for _, plist in data.items():
        for it in plist:
            sku = it.get("sku")
            if sku not in seen_skus:
                items.append(it)
                seen_skus.add(sku)

    # 2. Add static items ONLY if the SKU hasn't been seen yet
    for sku, p in CATALOG.items():
        if sku not in seen_skus:
            items.append({**p, "sku": sku})
            seen_skus.add(sku)

    return items


def get_any_product_by_sku(sku: str):
    if sku in CATALOG:
        return CATALOG[sku]
    data = storage.load_json(storage.SELLER_PRODUCTS_FILE)
    for _, items in data.items():
        for it in items:
            if it.get("sku") == sku:
                return it
    return None




# ==========================================
# SEARCH
# ==========================================
def _norm_text(s: str) -> str:
    s = str(s or "").lower()
    # keep letters/numbers/spaces only
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def search_products_by_name(query: str, include_sold_out: bool = True):
    q = _norm_text(query)
    if not q:
        return []

    tokens = [t for t in q.split(" ") if t]
    if not tokens:
        return []

    results = []
    for it in enumerate_all_products():
        if it.get("hidden", False):
            continue

        name_raw = it.get("name") or it.get("title") or ""
        sku_raw = it.get("sku") or ""

        hay = f"{_norm_text(name_raw)} {_norm_text(sku_raw)}"

        # require ALL tokens to appear somewhere
        if all(t in hay for t in tokens):
            stock = int(it.get("stock", 0) or 0)
            if include_sold_out or stock > 0:
                results.append(it)

    # sort by relevance: startswith first, then shorter name
    def score(it):
        name = _norm_text(it.get("name") or it.get("title") or "")
        starts = 0 if name.startswith(tokens[0]) else 1
        return (starts, len(name))

    results.sort(key=score)
    return results

async def ask_user_search(update, context):
    q = update.callback_query
    context.user_data["awaiting_search"] = "users"

    await q.edit_message_text(
        "👤 *Search Users*\n\nSend a *username* or *user ID*.",
        parse_mode="Markdown",
    )

async def ask_search(update, context):
    q = update.callback_query
    context.user_data["awaiting_search"] = "products"

    await q.edit_message_text(
        "🔍 *Search Products*\n\nSend a product name.",
        parse_mode="Markdown",
    )

async def show_user_search_results(update, context, results):
    msg = update.effective_message

    if not results:
        return await msg.reply_text("❌ No users found matching that ID or username.")

    blocks = []
    buttons = []

    for u in results:
        uid = u.get("user_id")
        uname = u.get("username") or "Anonymous"
        
        # Fetch items this specific user is selling
        user_items = [it for it in enumerate_all_products() if str(it.get("seller_id")) == str(uid)]
        
        item_list = ""
        if user_items:
            item_list = "\n".join([f"  ├ {it['emoji']} {it['name']} (${it['price']})" for it in user_items[:3]])
            if len(user_items) > 3: item_list += "\n  └ ... and more"
        else:
            item_list = "  └ _No active listings_"

        blocks.append(
            f"👤 **{uname}** (`{uid}`)\n"
            f"{item_list}"
        )

        buttons.append([
            InlineKeyboardButton(f"💬 Message {uname}", callback_data=f"chat:user:{uid}")
        ])

    buttons.append([InlineKeyboardButton("🏠 Home", callback_data="menu:main")])

    await msg.reply_text(
        "🔍 **User Search Results**\n" + "━" * 15 + "\n\n" + "\n\n".join(blocks),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

async def show_search_results(update, context, results):
    msg = update.effective_message

    if not results:
        return await msg.reply_text("❌ No products found. Try another name.")

    blocks = []
    rows = []

    for it in results[:10]:
        sku = it.get("sku")
        if not sku:
            continue

        name = it.get("name") or it.get("title") or "Unnamed"
        emoji = it.get("emoji", "📦")
        price = float(it.get("price", 0))
        stock = int(it.get("stock", 0))
        sid = it.get("seller_id", 0)

        seller_label = "System" if sid == 0 else f"User {sid}"
        stock_text = f"{stock} left" if stock > 0 else "SOLD OUT"

        blocks.append(
            f"{emoji} {name} — ${price:.2f}\n"
            f"Seller: {seller_label}\n"
            f"Stock: {stock_text}"
        )

        view_btn = InlineKeyboardButton(f"🔎 View {str(name)[:12]}", callback_data=f"view_item:{sku}")

        if stock > 0:
            cart_btn = InlineKeyboardButton(f"🛒 +Cart (${price:.2f})", callback_data=f"cart:add:{sku}")
            rows.append([view_btn, cart_btn])
        else:
            # no add-to-cart button when sold out
            rows.append([view_btn])


    rows.append([InlineKeyboardButton("🔍 Search Again", callback_data="shop:search")])
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="menu:main")])

    return await msg.reply_text(
        "🔍 Search Results\n\n" + "\n\n".join(blocks),
        reply_markup=InlineKeyboardMarkup(rows),
    )

# ==========================================
# MAIN MENU
# ==========================================
def build_main_menu(balance: float, uid: int = None):
    # prevent crash when uid is missing
    cart_count = 0

    try:
        if uid is not None:
            cart = shopping_cart.get_user_cart(uid)
            cart_count = sum(item.get("qty", 0) for item in cart.values())
    except:
        cart_count = 0

    cart_label = f"🛒 Cart ({cart_count})"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Marketplace", callback_data="menu:shop"),
         InlineKeyboardButton("📦 Orders", callback_data="menu:orders")],
        [InlineKeyboardButton(cart_label, callback_data="cart:view"),
         InlineKeyboardButton("💼 Wallet", callback_data="menu:wallet")],
        [InlineKeyboardButton("🛠 Sell", callback_data="menu:sell"),
         InlineKeyboardButton("✉ Messages", callback_data="menu:messages")],
        [InlineKeyboardButton("💬 Lounge", callback_data="chat:public_open"),
         InlineKeyboardButton("⚙ Functions", callback_data="menu:functions")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="menu:refresh")],
    ])

    text = (
        "🌀 *Xchange — Secure Escrow Marketplace*\n"
        "══════════════════════\n"
        f"💳 *Balance:* `${balance:.2f}`\n"
        "══════════════════════\n"
        "_Buy • Sell • Escrow • Trade Safely_\n"
    )

    return kb, text



# ==========================================
# SHOP PAGE (UPDATED WITH NEW ADD TO CART)
# ==========================================

def build_shop_keyboard(uid=None, page=0):
    all_items = [it for it in enumerate_all_products() if not it.get("hidden", False)]
    items_per_page = 5
    start_idx = page * items_per_page
    current_items = all_items[start_idx : start_idx + items_per_page]

    rows = []
    display_lines = []

    # fallback if uid missing
    viewer_id = int(uid) if uid else 0

    for it in current_items:
        sku = it["sku"]
        price = it["price"]
        stock = it.get("stock", 0)
        sid = it.get("seller_id", 0)

        seller_label = "System" if sid == 0 else f"User {sid}"
        stock_text = f"{stock} left" if stock > 0 else "🛑 *SOLD OUT*"

        display_lines.append(
            f"{it.get('emoji','📦')} **{it['name']}** — `${price:.2f}`\n"
            f"├ 👤 Seller: `{seller_label}`\n"
            f"└ 📦 Stock: {stock_text}"
        )

        view_btn = InlineKeyboardButton(f"🔎 View {it['name'][:12]}", callback_data=f"view_item:{sku}")

        # OWNER CAN’T BUY OWN ITEM
        if viewer_id == sid:
            rows.append([view_btn])                      # only “View”
        else:
            cart_btn = InlineKeyboardButton(f"🛒 +Cart (${price:.2f})", callback_data=f"cart:add:{sku}:shop")
            rows.append([view_btn, cart_btn])            # normal two buttons

    # Navigation & Footer
    nav = [InlineKeyboardButton(f"Page {page+1}", callback_data="noop")]
    if page > 0:
        nav.insert(0, InlineKeyboardButton("⬅️", callback_data=f"shop_page:{page-1}"))
    if start_idx + items_per_page < len(all_items):
        nav.append(InlineKeyboardButton("➡️", callback_data=f"shop_page:{page+1}"))
    rows.append(nav)

    rows.append([
        InlineKeyboardButton("🔍 Search", callback_data="shop:search"),
        InlineKeyboardButton("👤 Users", callback_data="search:users")
    ])
    rows.append([
        InlineKeyboardButton("🛒 Cart", callback_data="cart:view"),
        InlineKeyboardButton("🏠 Home", callback_data="menu:main")
    ])

    header = "🛍 **XCHANGE MARKETPLACE**\n" + "━" * 18 + "\n"
    return header + "\n\n".join(display_lines), InlineKeyboardMarkup(rows)

# ==========================================
# View Item Details Screen (Updated with Add-to-Cart qty)
# ==========================================
async def view_item_details(update, context, sku):
    from modules import shopping_cart

    q = update.callback_query
    item = get_any_product_by_sku(sku)
    if not item:
        return await q.answer("Item not found.", show_alert=True)

    uid = update.effective_user.id
    seller_id = int(item.get("seller_id", 0))

    user_cart = shopping_cart.get_user_cart(uid)
    current_qty = user_cart.get(sku, {}).get("qty", 0)
    add_label = "🛒 Add to Cart" if current_qty == 0 else f"🛒 Add to Cart ({current_qty})"

    seller_label = "System Admin" if seller_id == 0 else f"User {seller_id}"

    text = (
        f"{item.get('emoji','📦')} **{item['name']}**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 **Seller:** `{seller_label}`\n"
        f"💰 **Price:** `${item['price']:.2f}`\n"
        f"📋 **In Stock:** `{item.get('stock', 0)}` units\n\n"
        f"📝 **Description:**\n_{item.get('desc', 'No description provided.')}_"
    )

    # GUARD: seller can’t buy own item
    if uid == seller_id:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Analytics", callback_data=f"analytics:single:{sku}")],
            [InlineKeyboardButton("🔙 Back to Marketplace", callback_data="menu:shop")]
        ])
    else:
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(add_label, callback_data=f"cart:add:{sku}:view"),
                InlineKeyboardButton("💰 Buy Now", callback_data=f"buy:{sku}:1")
            ],
            [InlineKeyboardButton("🔙 Back to Marketplace", callback_data="menu:shop")]
        ])

    if item.get("image_url"):
        await q.message.delete()
        return await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=item["image_url"],
            caption=text,
            parse_mode="Markdown",
            reply_markup=kb
        )

    await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

# ==========================================
# STRIPE — CART CHECKOUT
# ==========================================
async def stripe_cart_checkout(update, context, total_str):
    q = update.callback_query
    uid = update.effective_user.id   
    cart = shopping_cart.get_user_cart(uid)
    if not cart:
        return await q.answer("Cart is empty.", show_alert=True)

    # Build items list
    items = [{"sku": sku, "qty": int(item.get("qty", 1) or 1)} for sku, item in cart.items()]

    # Create order first
    order_id = storage.add_order(
        buyer_id=uid,
        item_name="Cart",
        qty=sum(i["qty"] for i in items),
        amount=float(total_str),
        method="stripe_cart",
        seller_id=0
    )

    ok, msg = inventory.reserve_cart_for_payment(order_id, items)
    if not ok:
        storage.update_order_status(order_id, "failed", reason=msg)
        return await q.answer(f"❌ {msg}", show_alert=True)

    # Send invoice with cart payload
    provider_token = os.getenv("PROVIDER_TOKEN_STRIPE")
    price_in_cents = int(float(total_str) * 100)

    await context.bot.send_invoice(
        chat_id=uid,
        title="Order: Cart",
        description="Checkout your cart",
        payload=f"PAYCART|{order_id}",
        provider_token=provider_token,
        currency="SGD",
        prices=[LabeledPrice("Total Price", price_in_cents)],
        start_parameter="market-cart-checkout"
    )
    return await q.answer()

# ==========================================
# SINGLE ITEM BUY — UI
# ==========================================
async def on_buy(update, context, sku, qty):
    q = update.callback_query
    item = get_any_product_by_sku(sku)

    if not item:
        return await q.answer("Item missing", show_alert=True)

    qty = clamp_qty(qty)
    total = float(item["price"]) * qty

    # FORMAT: pay_native:provider:amount:sku
    # Fixed syntax: added comma after Solana button and removed extra parentheses
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Stripe", callback_data=f"pay_native:stripe:{total}:{sku}:{qty}")],
        [InlineKeyboardButton("🌐 Smart Glocal", callback_data=f"pay_native:smart_glocal:{total}:{sku}")],
        [InlineKeyboardButton("🚀 Pay with Solana (SOL)", callback_data=f"pay_crypto:solana:{total:.2f}:{sku}")],
        [InlineKeyboardButton("🇪🇸 Redsys", callback_data=f"pay_native:redsys:{total:.2f}:{sku}")],
        [InlineKeyboardButton("🇸🇬 PayNow (HitPay)", callback_data=f"hitpay:{sku}:{qty}")], 
        [InlineKeyboardButton("🔙 Back", callback_data="menu:shop")],
    ])

    txt = (
        f"{item.get('emoji')} *{item['name']}*\n"
        f"Qty: *{qty}*\nTotal: *SGD {total:.2f}*" 
    )

    await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=kb)


# ==========================================
# QUANTITY CHANGE SCREEN
# ==========================================
def clamp_qty(qty, min_qty: int = 1, max_qty: int = 99) -> int:
    """
    Normalizes qty into a safe integer range.
    Accepts int/float/str like "3", "3.0", etc.
    """
    try:
        q = int(qty)
    except Exception:
        try:
            q = int(float(str(qty).strip()))
        except Exception:
            q = min_qty

    if q < min_qty:
        return min_qty
    if q > max_qty:
        return max_qty
    return q

async def on_qty(update, context, sku, qty):
    q = update.callback_query
    item = get_any_product_by_sku(sku)
    
    if not item:
        return await q.answer("Item no longer available.", show_alert=True)

    # 1. Clamp quantity between 1 and 99
    qty = clamp_qty(qty)
    
    # 2. Check Inventory Stock (Prevent user from selecting more than available)
    # This uses the inventory module imported in your bot.py
    ok, stock_left = inventory.check_stock(sku, qty)
    if not ok:
        await q.answer(f"⚠️ Only {stock_left} items in stock.", show_alert=True)
        # Re-clamp to max available stock
        qty = stock_left if stock_left > 0 else 1

    total = float(item["price"]) * qty

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("−", callback_data=f"qty:{sku}:{qty-1}"),
            # 'noop' callback data prevents the button from triggering an error
            InlineKeyboardButton(f"Qty: {qty}", callback_data="noop"), 
            InlineKeyboardButton("+", callback_data=f"qty:{sku}:{qty+1}"),
        ],
        [InlineKeyboardButton(f"✅ Checkout — ${total:.2f}", callback_data=f"checkout:{sku}:{qty}")],
        [InlineKeyboardButton("🔙 Back to Shop", callback_data="menu:shop")],
    ])

    await q.edit_message_text(
        f"🛒 *Confirm Quantity*\n\n"
        f"📦 *Product:* {item.get('emoji', '🛍')} {item['name']}\n"
        f"💰 *Price:* `${item['price']:.2f}`\n"
        f"🔢 *Selected:* `{qty}`\n"
        f"══════════════════════\n"
        f"💵 *Total:* `${total:.2f}`",
        reply_markup=kb,
        parse_mode="Markdown",
    )

# ==========================================
# Show Captcha Screen
# ==========================================

async def show_captcha(update, context, captcha_text):
    # This generates buttons for a simple captcha
    options = ["123", "ABC", captcha_text, "XYZ"] # Simplified logic
    import random
    random.shuffle(options)
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(opt, callback_data=f"captcha:{opt}") for opt in options]
    ])
    
    await update.callback_query.edit_message_text(
        "🛡 *Security Verification*\n\nPlease select the correct code to verify you are human:",
        reply_markup=kb,
        parse_mode="Markdown"
    )

# ==========================================
# CHECKOUT → calls BUY screen again
# ==========================================
async def on_checkout(update, context, sku, qty):
    # This redirects the user to the payment method selection screen (on_buy)
    # We re-verify stock one last time before showing payment options
    ok, stock = inventory.check_stock(sku, qty)
    if not ok:
        return await update.callback_query.answer(f"Out of stock! Only {stock} left.", show_alert=True)
        
    return await on_buy(update, context, sku, qty)

# ==========================================
#  Check Order Status in orders.json
# ==========================================

async def handle_start_deep_link(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str):
    uid = update.effective_user.id
    
    if payload.startswith("success_"):
        order_id = payload.replace("success_", "")
        
        # 1. Load orders to verify status
        orders = storage.load_json(storage.ORDERS_FILE)
        order_info = orders.get(order_id)

        if order_info and order_info.get("status") == "escrow_hold":
            text = (
                "✅ **Payment Verified!**\n"
                f"Order `{order_id}` is now held in **Escrow**.\n\n"
                "The seller has been notified to fulfill your order. "
                "Funds will only be released once you confirm receipt."
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📦 View Order Status", callback_data="menu:orders")],
                [InlineKeyboardButton("🏠 Main Menu", callback_data="menu:main")]
            ])
        else:
            # If the webhook hasn't arrived yet, show a 'processing' message
            text = (
                "⏳ **Processing Payment...**\n"
                f"We've received your return for Order `{order_id}`.\n\n"
                "It may take a moment for the payment provider to notify us. "
                "Please check your Orders menu in a few seconds."
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh Orders", callback_data="menu:orders")]])

        ok, msg = inventory.confirm_payment(order_id)
        if not ok:
            await update.message.reply_text(f"⚠️ Inventory confirm failed: {msg}", parse_mode="Markdown")

# ==========================================
# Handle Post Completion
# ==========================================

async def handle_post_completion_dispute(update, context, oid):
    q = update.callback_query
    uid = update.effective_user.id

    # 1. mark disputed
    storage.update_order_status(oid, "disputed")

    # 2. notify admin
    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"🚨 **Post-completion dispute**\n"
            f"Order: `{oid}`\n"
            f"By user: `{uid}`",
            parse_mode="Markdown"
        )
    except:
        pass

    await q.answer("⚖️ Dispute filed. An admin will review it.", show_alert=True)
    return await on_menu(update, context, force_tab="orders")

# ==========================================
# STRIPE — SINGLE ITEM
# ==========================================
async def create_stripe_checkout(update, context, sku, qty):
    q = update.callback_query
    item = get_any_product_by_sku(sku)

    if not item:
        return await q.answer("❌ Item no longer available.", show_alert=True)

    qty = clamp_qty(qty)
    total = float(item["price"]) * qty
    user_id = update.effective_user.id

    stripe_token = os.getenv("PROVIDER_TOKEN_STRIPE")
    if not stripe_token:
        return await q.answer("❌ Stripe is currently unavailable (Token missing).", show_alert=True)

    try:
        price_in_cents = int(total * 100)

        # 1) Create order and get real order_id
        order_id = storage.add_order(
            buyer_id=user_id,
            item_name=item["name"],
            qty=qty,
            amount=total,
            method="Stripe",
            seller_id=int(item.get("seller_id", 0)),
        )

        # 2) Reserve inventory before sending invoice
        ok, msg = inventory.reserve_for_payment(order_id, sku, qty)
        if not ok:
            storage.update_order_status(order_id, "failed", reason=msg)
            return await q.answer(f"❌ {msg}", show_alert=True)

        # 3) Put order_id into invoice payload
        payload = f"PAY|{order_id}|{sku}|{qty}"

        await context.bot.send_invoice(
            chat_id=user_id,
            title=f"Buy {item['name']}",
            description=f"Quantity: {qty} | Secure checkout via Stripe",
            payload=payload,
            provider_token=stripe_token,
            currency="SGD",
            prices=[LabeledPrice(f"{item['name']} x{qty}", price_in_cents)],
            start_parameter="stripe-purchase",
        )

        await q.answer()

    except Exception as e:
        logger.error(f"Stripe Native Error: {e}")
        await q.edit_message_text(f"❌ Could not initialize Stripe: {e}")

# ==========================================
# HitPay Checkout - Single Item
# ==========================================                                                                  

async def create_hitpay_checkout(update, context, sku, qty):
    import requests

    q = update.callback_query
    item = get_any_product_by_sku(sku)
    if not item:
        return await q.answer("❌ Item no longer available.", show_alert=True)

    qty = clamp_qty(qty)
    total = float(item["price"]) * qty
    user_id = update.effective_user.id

    # 1) Create order first and use its id everywhere
    order_id = storage.add_order(
        buyer_id=user_id,
        item_name=item["name"],
        qty=qty,
        amount=total,
        method="HitPay",
        seller_id=int(item.get("seller_id", 0)),
    )

    # 2) Reserve stock now
    ok, msg = inventory.reserve_for_payment(order_id, sku, qty)
    if not ok:
        storage.update_order_status(order_id, "failed", reason=msg)
        return await q.answer(f"❌ {msg}", show_alert=True)

    try:
        SERVER_BASE = os.getenv("SERVER_BASE_URL", "").rstrip("/")
        if not SERVER_BASE:
            inventory.release_on_failure_or_refund(order_id, reason="missing_server_base")
            storage.update_order_status(order_id, "failed", reason="SERVER_BASE_URL missing")
            return await q.edit_message_text("❌ SERVER_BASE_URL not set in .env")

        res = requests.post(
            f"{SERVER_BASE}/hitpay/create_payment",
            json={
                "order_id": order_id,          # IMPORTANT
                "amount": total,
                "user_id": user_id,
                "description": item["name"],
            },
            timeout=15,
        )
        res.raise_for_status()
        data = res.json()
        payment_url = data.get("checkout_url")

        if not payment_url:
            raise Exception(f"Invalid HitPay response: {data}")

    except Exception as e:
        inventory.release_on_failure_or_refund(order_id, reason=f"hitpay_create_failed:{e}")
        storage.update_order_status(order_id, "failed", reason=str(e))
        return await q.edit_message_text(f"❌ HitPay error: {e}")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇸🇬 Pay with PayNow", url=payment_url)],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu:shop")],
    ])

    await q.edit_message_text(
        f"*HitPay Checkout*\nItem: {item['name']}\nQty: {qty}\nTotal: ${total:.2f}\n\nOrder: `{order_id}`",
        reply_markup=kb,
        parse_mode="Markdown",
    )


# ==========================================
# HITPAY CHECKOUT - CART
# ==========================================

async def create_hitpay_cart_checkout(update, context, total):
    import requests

    q = update.callback_query
    user_id = update.effective_user.id
    total = float(total)

    # 1) Create a cart order first (single order_id)
    order_id = storage.add_order(
        buyer_id=user_id,
        item_name="Cart Items",
        qty=1,
        amount=total,
        method="HitPay",
        seller_id=0,
    )

    #  reserve each cart item here if cart uses real SKUs.
    # (Optional: implement per-item reservation logic here)

    try:
        SERVER_BASE = os.getenv("SERVER_BASE_URL", "").rstrip("/")
        if not SERVER_BASE:
            storage.update_order_status(order_id, "failed", reason="SERVER_BASE_URL missing")
            return await q.edit_message_text("❌ SERVER_BASE_URL not set in .env")

        res = requests.post(
            f"{SERVER_BASE}/hitpay/create_payment",
            json={
                "order_id": order_id,          # IMPORTANT
                "amount": total,
                "user_id": user_id,
                "description": "Cart Checkout",
            },
            timeout=15,
        )
        res.raise_for_status()
        data = res.json()
        payment_url = data.get("checkout_url") or data.get("payment_url")

        if not payment_url:
            raise Exception(f"Invalid HitPay response: {data}")

    except Exception as e:
        storage.update_order_status(order_id, "failed", reason=str(e))
        return await q.edit_message_text(f"❌ HitPay error: {e}")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇸🇬 Pay with HitPay", url=payment_url)],
        [InlineKeyboardButton("❌ Cancel", callback_data="cart:view")],
    ])

    await q.edit_message_text(
        f"*HitPay Cart Checkout*\nTotal: ${total:.2f}\n\nOrder: `{order_id}`",
        reply_markup=kb,
        parse_mode="Markdown",
    )

# ==========================================
# FUNCTIONS PANEL  (your original)
# ==========================================
async def show_functions_menu(update, context):
    q = update.callback_query
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Disputes (Admin)", callback_data="admin:disputes")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")]
    ])
    await q.edit_message_text(
        "⚙️ *Functions Panel*\nAdmin tools + utilities.",
        reply_markup=kb,
        parse_mode="Markdown"
    )

# ==========================================
# Admin Dispute Dashboard  (links from Functions)
# ==========================================
async def admin_dispute_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id

    if uid != ADMIN_ID:
        return await q.answer("🚫 Access Denied", show_alert=True)

    orders = storage.load_json(storage.ORDERS_FILE)          # dict  ord_id -> dict
    disputes = [o for o in orders.values() if o.get("status") == "disputed"]

    if not disputes:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="menu:main")]])
        return await q.edit_message_text("✅ No open disputes.", reply_markup=kb)

    lines   = ["⚖️ *Open Disputes*"]
    buttons = []

    for o in disputes[:10]:          # cap at 10
        oid   = o["id"]
        buyer = o["buyer_id"]
        seller= o["seller_id"]
        amt   = float(o["amount"])
        sku   = o.get("item", "Item")

        lines.append(
            f"\n`{oid}`\n"
            f"💰 ${amt:.2f}  ┊  📦 {sku}\n"
            f"👤 Buyer `{buyer}`  ┊  🏪 Seller `{seller}`"
        )

        buttons.append([
            InlineKeyboardButton(f"✅ Release {oid}", callback_data=f"admin_release:{oid}"),
            InlineKeyboardButton(f"💰 Refund {oid}",  callback_data=f"admin_refund:{oid}"),
            InlineKeyboardButton(f"💬 Chat",         callback_data=f"chat:order:{oid}")
        ])

    buttons.append([InlineKeyboardButton("🏠 Functions", callback_data="menu:functions")])
    kb = InlineKeyboardMarkup(buttons)
    await q.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=kb)   


# ==========================================
# MENU ROUTER
# ==========================================
def _safe_int(v, default=0):
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return default

def _safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        try:
            s = str(v)
            s = s.replace("$", "").replace("SGD", "").strip()
            return float(s)
        except Exception:
            return default
        

async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, force_tab: str = None):
    q = update.callback_query
    _, tab = q.data.split(":", 1)
    uid = update.effective_user.id

    # ---------- helper ----------
    async def safe_edit(text, kb):
        try:
            return await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        except Exception as e:
            logger.warning("safe_edit: %s – sending fresh message", e)
            return await context.bot.send_message(
                uid, text, reply_markup=kb, parse_mode="Markdown"
            )

    # ---------- emoji quick-map ----------
    emoji = {
        "pending": "⏳", "awaiting_payment": "⏳", "escrow_hold": "🔒",
        "shipped": "🚚", "completed": "✅", "disputed": "⚖️",
        "refunded": "💰", "cancelled": "❌", "expired": "🕰",
    }

    # =========================================================================
    #  SHOP
    # =========================================================================
    if tab == "shop":
        txt, kb = build_shop_keyboard(uid=uid)
        return await safe_edit(txt, kb)

    # =========================================================================
    #  CART
    # =========================================================================
    if tab == "cart":
        return await shopping_cart.view_cart(update, context)

    # =========================================================================
    #  WALLET
    # =========================================================================
    if tab == "wallet":
        local_bal = storage.get_balance(uid)
        user_wallet = wallet_utils.ensure_user_wallet(uid)
        on_chain = wallet_utils.get_balance_devnet(user_wallet["public_key"])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Deposit / View Address", callback_data="wallet:deposit")],
            [InlineKeyboardButton("📤 Withdraw SOL", callback_data="wallet:withdraw")],
            [InlineKeyboardButton("🏠 Home", callback_data="menu:main")]
        ])
        return await safe_edit(
            f"💼 **Wallet Dashboard**\n\n"
            f"💳 **Stored Balance:** `${local_bal:.2f}`\n"
            f"🧪 **Solana Devnet:** `{on_chain:.4f} SOL`\n\n"
            f"📍 **Public Key:**\n`{user_wallet['public_key']}`",
            kb,
        )

    # =========================================================================
    #  MESSAGES
    # =========================================================================
    if tab == "messages":
        threads = storage.load_json(storage.MESSAGES_FILE)
        buttons = []
        for k, v in threads.items():
            if uid in (v.get("buyer_id"), v.get("seller_id")) and uid not in v.get("hidden_from", []):
                name = v.get("product", {}).get("name", "Chat")
                buttons.append([
                    InlineKeyboardButton(f"💬 {name}", callback_data=f"chat:open:{k}"),
                    InlineKeyboardButton("🗑", callback_data=f"chat:delete:{k}")
                ])
        buttons.append([InlineKeyboardButton("🏠 Home", callback_data="menu:main")])
        msg_text = "💌 *Your Conversations*\n" + "━" * 15 + "\n"
        if len(buttons) == 1:
            msg_text += "_No active messages._"
        return await safe_edit(msg_text, InlineKeyboardMarkup(buttons))

    # =========================================================================
    #  ORDERS  (the one that was failing)
    # =========================================================================
    if tab == "orders":
        storage.expire_stale_pending_orders(expire_seconds=900)
        orders = storage.list_orders_for_user(uid)
        if not orders:
            txt = "📦 *Orders*\n\n_No orders yet._"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Refresh", callback_data="menu:orders"),
                 InlineKeyboardButton("🏠 Home", callback_data="menu:main")]
            ])
            return await safe_edit(txt, kb)

        orders = sorted(orders, key=lambda o: int(o.get("ts", 0)), reverse=True)
        lines, buttons = ["📦 *Your Order History*"], []

        for o in orders[:12]:
            oid   = o.get("id", "???")
            item  = o.get("item", "Product")
            qty   = o.get("qty", 1)
            amt   = float(o.get("amount", 0))
            stat  = str(o.get("status", "pending")).lower()
            lines.append(f"{emoji.get(stat, '❓')} `{oid}`  {item} ×{qty}  ‑  *${amt:.2f}*")

            row = [InlineKeyboardButton("💬 Chat", callback_data=f"chat:order:{oid}")]
            if stat in ("pending", "awaiting_payment"):
                row.append(InlineKeyboardButton("❌ Cancel", callback_data=f"ordercancel:{oid}"))
            elif stat in ("escrow_hold", "shipped"):
                row.append(InlineKeyboardButton("✅ Received", callback_data=f"order_complete:{oid}"))
            elif stat == "completed":
                row.append(InlineKeyboardButton("⚖️ Dispute", callback_data=f"dispute_after:{oid}"))
            elif stat in ("refunded", "cancelled", "expired"):
                row.append(InlineKeyboardButton("🗄 Archive", callback_data=f"orderarchive:{oid}"))
            buttons.append(row)

            # seller extras
            if int(o.get("seller_id", 0)) == uid:
                s_row = []
                if stat == "escrow_hold":
                    s_row.append(InlineKeyboardButton("📦 Ship", callback_data=f"seller:ship:{oid}"))
                if stat in ("disputed", "completed", "refunded", "cancelled", "expired"):
                    s_row.append(InlineKeyboardButton("📊 Analytics", callback_data=f"analytics:single:{oid}"))
                if s_row:
                    buttons.append(s_row)

        buttons.append([
            InlineKeyboardButton("🔄 Refresh", callback_data="menu:orders"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="menu:orders:main")
        ])
        return await safe_edit("\n".join(lines), InlineKeyboardMarkup(buttons))

    # =========================================================================
    #  SELL
    # =========================================================================
    if tab == "sell":
        txt, kb = seller.build_seller_menu(storage.get_role(uid))
        return await safe_edit(txt, kb)

    # =========================================================================
    #  FUNCTIONS
    # =========================================================================
   
    if tab == "functions":
        return await show_functions_menu(update, context)

    # =========================================================================
    #  MAIN / REFRESH
    # =========================================================================
    if tab in ("main", "refresh"):
        kb, txt = build_main_menu(storage.get_balance(uid), uid)
        return await safe_edit(txt, kb)

    # unknown tab – go home
    kb, txt = build_main_menu(storage.get_balance(uid), uid)
    return await safe_edit(txt, kb)