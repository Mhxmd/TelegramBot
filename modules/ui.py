

import os
import qrcode
import re
from io import BytesIO
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from typing import Optional
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
    for sku, p in CATALOG.items():
        items.append({**p, "sku": sku})

    data = storage.load_json(storage.SELLER_PRODUCTS_FILE)
    for _, plist in data.items():
        for it in plist:
            items.append(it)

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

    for it in current_items:
        sku = it["sku"]
        price = it["price"]
        stock = it.get("stock", 0)
        sid = it.get("seller_id", 0)
        
        seller_label = "System" if sid == 0 else f"User {sid}"
        stock_text = f"{stock} left" if stock > 0 else "🛑 *SOLD OUT*"
        
        # TREE FORMAT:
        # Using ├ for the seller and └ for the "Action" line to point at buttons
        display_lines.append(
            f"{it.get('emoji','📦')} **{it['name']}** — `${price:.2f}`\n"
            f"├ 👤 Seller: `{seller_label}`\n"
            f"└ 📦 Stock: {stock_text}"
        )

        # SIDE-BY-SIDE BUTTONS:
        # Left button shows the name, Right button shows the action + price
        # We use .ljust() or short strings to keep them from stacking
        rows.append([
            InlineKeyboardButton(f"🔎 View {it['name'][:12]}", callback_data=f"view_item:{sku}"),
            InlineKeyboardButton(f"🛒 +Cart (${price:.2f})", callback_data=f"cart:add:{sku}")
        ])

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
    # Added \n\n to separate each product "tree" clearly
    return header + "\n\n".join(display_lines), InlineKeyboardMarkup(rows)

# ==========================================
# View Item Details Screen
# ==========================================

async def view_item_details(update, context, sku):
    q = update.callback_query
    item = get_any_product_by_sku(sku)
    
    if not item:
        return await q.answer("Item not found.", show_alert=True)

    seller_id = item.get("seller_id", 0)
    seller_label = "System Admin" if seller_id == 0 else f"User {seller_id}"
    
    # FIX: Ensure this string is assigned (=), not appended (+=) inside a loop
    text = (
        f"{item.get('emoji','📦')} **{item['name']}**\n"
        f"━━━━━━━━━━━━━━━\n"
        f"👤 **Seller:** `{seller_label}`\n"
        f"💰 **Price:** `${item['price']:.2f}`\n"
        f"📋 **In Stock:** `{item.get('stock', 0)}` units\n\n"
        f"📝 **Description:**\n_{item.get('desc', 'No description provided.')}_"
    )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛒 Add to Cart", callback_data=f"cart:add:{sku}"),
            InlineKeyboardButton("💰 Buy Now", callback_data=f"buy:{sku}:1")
        ],
        [InlineKeyboardButton("🔙 Back to Marketplace", callback_data="menu:shop")]
    ])

    # Smooth transition: Delete old menu and send new photo card
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
async def stripe_cart_checkout(update, context, total):
    import requests, time
    q = update.callback_query
    uid = update.effective_user.id
    
    # Check if we are in a cart flow or single item flow
    is_cart = "Cart" in (q.data or "")
    order_id = f"{'cart' if is_cart else 'sku'}_{uid}_{int(time.time())}"
    
    await q.answer("Connecting to Stripe...")

    try:
        SERVER_BASE = os.getenv("SERVER_BASE_URL", "").rstrip("/")
        if not SERVER_BASE:
            return await q.edit_message_text("❌ SERVER_BASE_URL not set in .env")

        res = requests.post(
            f"{SERVER_BASE}/create_checkout_session",
            json={
                "order_id": order_id,
                "amount": float(total),
                "user_id": uid
            },
            timeout=15
        )
        
        # If this fails with 404, it means server.py isn't handling this URL correctly
        res.raise_for_status() 
        
        data = res.json()
        checkout_url = data["checkout_url"]

        storage.add_order(uid, "Stripe Purchase", 1, float(total), "Stripe", 0)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Pay Securely Now", url=checkout_url)],
            [InlineKeyboardButton("🔙 Back", callback_data="cart:view" if is_cart else "menu:shop")],
        ])

        await q.edit_message_text(
            f"🧾 *Secure Checkout*\n\nTotal: *SGD {float(total):.2f}*\n\n"
            "Click below to pay via our secure Stripe portal.",
            reply_markup=kb,
            parse_mode="Markdown",
        )

    except requests.exceptions.HTTPError as e:
        # This will specifically tell you if it's a 404 (wrong URL) or 500 (server crash)
        print(f"Server Error: {e}") 
        return await q.edit_message_text(f"❌ Payment Server Error ({res.status_code}). Please check if server.py is running.")
    except Exception as e:
        print(f"General Error: {e}")
        return await q.edit_message_text(f"❌ Connection Failed: {e}")
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
        [InlineKeyboardButton("💳 Stripe", callback_data=f"pay_native:stripe:{total}:{sku}")],
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

        await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

# ==========================================
# STRIPE — SINGLE ITEM
# ==========================================
async def create_stripe_checkout(update, context, sku, qty):
    """
    Switched from external Flask server to Native Telegram Invoice.
    This fixes the 404 error by bypassing the ngrok /create_checkout_session URL.
    """
    q = update.callback_query
    item = get_any_product_by_sku(sku)
    
    if not item:
        return await q.answer("❌ Item no longer available.", show_alert=True)

    qty = clamp_qty(qty)
    total = float(item["price"]) * qty
    user_id = update.effective_user.id
    
    # Get the live Stripe token from environment
    stripe_token = os.getenv("PROVIDER_TOKEN_STRIPE")
    
    if not stripe_token:
        return await q.answer("❌ Stripe is currently unavailable (Token missing).", show_alert=True)

    try:
        # Convert to cents for Stripe/Telegram
        price_in_cents = int(total * 100)
        
        # 1. Add record to your database
        storage.add_order(user_id, item["name"], qty, total, "Stripe", int(item.get("seller_id", 0)))

        # 2. Send the native Telegram invoice
        await context.bot.send_invoice(
            chat_id=user_id,
            title=f"Buy {item['name']}",
            description=f"Quantity: {qty} | Secure checkout via Stripe",
            payload=f"PAY|{user_id}|{sku}",
            provider_token=stripe_token,
            currency="SGD", # Matches your dashboard currency
            prices=[LabeledPrice(f"{item['name']} x{qty}", price_in_cents)],
            start_parameter="stripe-purchase"
        )
        
        # Close the callback query to stop the loading spinner
        await q.answer()
        
    except Exception as e:
        logger.error(f"Stripe Native Error: {e}")
        await q.edit_message_text(f"❌ Could not initialize Stripe: {e}")

#HitPay Checkout - Single Item

async def create_hitpay_checkout(update, context, sku, qty):
    import requests, time

    q = update.callback_query
    item = get_any_product_by_sku(sku)
    qty = clamp_qty(qty)
    total = float(item["price"]) * qty
    user_id = update.effective_user.id
    order_id = f"ord_{user_id}_{int(time.time())}"

    try:
        SERVER_BASE = os.getenv("SERVER_BASE_URL", "").rstrip("/")

        res = requests.post(
            f"{SERVER_BASE}/hitpay/create_payment",
            json={
                "order_id": order_id,
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
        return await q.edit_message_text(f"❌ HitPay error: {e}")

    storage.add_order(
        user_id,
        item["name"],
        qty,
        total,
        "HitPay",
        int(item.get("seller_id", 0)),
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇸🇬 Pay with PayNow", url=payment_url)],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu:shop")],
    ])

    await q.edit_message_text(
        f"*HitPay Checkout*\nItem: {item['name']}\nQty: {qty}\nTotal: ${total:.2f}",
        reply_markup=kb,
        parse_mode="Markdown",
    )

#HitPay Checkout - Cart

async def create_hitpay_cart_checkout(update, context, total):
    import requests, time
    q = update.callback_query
    user_id = update.effective_user.id
    order_id = f"cart_{user_id}_{int(time.time())}"

    try:
        SERVER_BASE = os.getenv("SERVER_BASE_URL", "").rstrip("/")
        res = requests.post(
            f"{SERVER_BASE}/hitpay/create_payment",
            json={
                "order_id": order_id,
                "amount": float(total),
                "user_id": user_id,
                "description": "Cart Checkout",
            },
            timeout=15,
        )
        res.raise_for_status()
        data = res.json()
        # Use checkout_url to match your server logic
        payment_url = data.get("checkout_url") or data.get("payment_url") 

    except Exception as e:
        return await q.edit_message_text(f"❌ HitPay error: {e}")

    storage.add_order(user_id, "Cart Items", 1, float(total), "HitPay", 0)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇸🇬 Pay with HitPay", url=payment_url)],
        [InlineKeyboardButton("❌ Cancel", callback_data="cart:view")],
    ])

    await q.edit_message_text(
        f"*HitPay Cart Checkout*\nTotal: ${float(total):.2f}",
        reply_markup=kb,
        parse_mode="Markdown",
    )




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

    async def safe_edit(text, kb):
        try:
            return await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        except:
            return await context.bot.send_message(uid, text, reply_markup=kb, parse_mode="Markdown")

    if tab == "shop":
        txt, kb = build_shop_keyboard()
        return await safe_edit(txt, kb)

    if tab == "cart":
        return await shopping_cart.view_cart(update, context)

    if tab == "wallet":
        # 1. Get the local stored balance (e.g., USD/Credits)
        local_bal = storage.get_balance(uid) 
        
        # 2. Get the Solana wallet info
        user_wallet = wallet_utils.ensure_user_wallet(uid)
        pub = user_wallet["public_key"]
        
        # 3. Get actual SOL balance from Devnet
        on_chain = wallet_utils.get_balance_devnet(pub)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Deposit / View Address", callback_data="wallet:deposit")],
            [InlineKeyboardButton("📤 Withdraw SOL", callback_data="wallet:withdraw")],
            [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
        ])

        return await safe_edit(
            f"💼 **Wallet Dashboard**\n\n"
            f"💳 **Stored Balance:** `${local_bal:.2f}`\n"
            f"🧪 **Solana Devnet:** `{on_chain:.4f} SOL`\n\n"
            f"📍 **Public Key:**\n`{pub}`",
            kb,
        )

    if tab == "messages":
        threads = storage.load_json(storage.MESSAGES_FILE)
        buttons = []
        
        # Filter threads involving the current user
        user_threads = {k: v for k, v in threads.items() if uid in (v.get("buyer_id"), v.get("seller_id"))}

        for k, v in user_threads.items():
            # Skip if the user has already 'deleted' (hidden) this thread locally
            if uid in v.get("hidden_from", []):
                continue

            product_name = v.get("product", {}).get("name", "Unknown Item")
            
            # Create a row with: [ Open Chat ] [ Delete ]
            buttons.append([
                InlineKeyboardButton(f"💬 {product_name}", callback_data=f"chat:open:{k}"),
                InlineKeyboardButton(f"🗑", callback_data=f"chat:delete:{k}")
            ])

        buttons.append([InlineKeyboardButton("🏠 Home", callback_data="menu:main")])
        
        msg_text = "💌 *Your Conversations*\n" + "━" * 15 + "\n"
        if len(buttons) <= 1: # Only 'Home' button exists
            msg_text += "_No active messages._"
            
        return await safe_edit(msg_text, InlineKeyboardMarkup(buttons))
    
    if tab == "orders":
            # 1. Cleanup old unpaid orders
            storage.expire_stale_pending_orders(expire_seconds=900)

            orders = storage.list_orders_for_user(uid)

            if not orders:
                txt = "📦 *Orders*\n\nNo orders yet."
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="menu:main")]])
                return await safe_edit(txt, kb)

            # 2. Sort by newest first
            orders = sorted(orders, key=lambda o: int(o.get("ts", 0)), reverse=True)

            lines = ["📦 *Your Order History*", "━" * 15]
            buttons = []

            for o in orders[:15]:
                oid = o.get("id", "unknown")
                item = o.get("item", "Product")
                qty = o.get("qty", 1)
                amt = float(o.get("amount", 0))
                status = str(o.get("status", "pending")).lower()
                
                status_map = {
                    "pending": "⏳ Awaiting Payment",
                    "escrow_hold": "🔒 Held in Escrow",
                    "completed": "✅ Completed",
                    "disputed": "⚖️ Under Dispute",
                    "refunded": "💰 Refunded",
                    "cancelled": "❌ Cancelled",
                    "expired": "❓ Expired"
                }
                status_text = status_map.get(status, f"❓ {status.title()}")

                lines.append(f"\n🆔 `{oid}`\n└ {item} (x{qty}) — `${amt:.2f}`\n   Status: *{status_text}*")

                # --- 3. Action Buttons ---
                
                # Active Escrow: Buyer can release funds or dispute
                if status == "escrow_hold":
                    buttons.append([
                        InlineKeyboardButton(f"🤝 Confirm Receipt {oid}", callback_data=f"order_complete:{oid}")
                    ])
                    buttons.append([
                        InlineKeyboardButton(f"⚠️ Dispute / Chat", callback_data=f"chat:order:{oid}")
                    ])
                
                # Completed: Buyer can still dispute if something is wrong
                elif status == "completed":
                    buttons.append([
                        InlineKeyboardButton(f"⚖️ Dispute Completed Order {oid}", callback_data=f"dispute_after:{oid}"),
                        InlineKeyboardButton(f"🗄 Archive", callback_data=f"orderarchive:{oid}")
                    ])

                # Pending: Only option is to cancel
                elif status in ("pending", "awaiting_payment"):
                    buttons.append([
                        InlineKeyboardButton(f"❌ Cancel {oid}", callback_data=f"ordercancel:{oid}")
                    ])

                # Other finished states: Just archive
                elif status in ("refunded", "cancelled", "expired"):
                    buttons.append([
                        InlineKeyboardButton(f"🗄 Archive {oid}", callback_data=f"orderarchive:{oid}")
                    ])

            txt = "\n".join(lines)
            buttons.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu:main")])
            
            kb = InlineKeyboardMarkup(buttons)
            return await safe_edit(txt, kb)

    if tab == "sell":
        txt, kb = seller.build_seller_menu(storage.get_role(uid))
        return await safe_edit(txt, kb)

    if tab == "functions":
        return await show_functions_menu(update, context)

    if tab in ("main", "refresh"):
        kb, txt = build_main_menu(storage.get_balance(uid), uid)
        return await safe_edit(txt, kb)


    
# ==========================================
# Handling Post-Completion Disputes
# ==========================================

async def handle_post_completion_dispute(update, context, oid):
    query = update.callback_query
    uid = update.effective_user.id
    
    # Update status to disputed so it appears in the Admin Panel
    storage.update_order_status(oid, "disputed")
    
    # Notify Admin (Assuming you have an ADMIN_ID variable)
    admin_msg = (
        f"🚨 **URGENT: Post-Completion Dispute**\n\n"
        f"Order ID: `{oid}`\n"
        f"User: `{uid}`\n"
        f"Note: This order was already marked as COMPLETED. "
        f"Admin intervention required to check seller balance."
    )
    
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_msg, parse_mode="Markdown")
    except:
        pass

    await query.answer("⚖️ Dispute filed. An admin will review this transaction.", show_alert=True)
    return await on_menu(update, context, force_tab="orders")

# ==========================================
# Chat Delete
# ==========================================

# New helper function in ui.py
async def show_messages_menu(update, context):
    uid = update.effective_user.id
    threads = storage.load_json(storage.MESSAGES_FILE)
    buttons = []
    
    for k, v in threads.items():
        # Check if current user is part of chat AND hasn't hidden it
        if uid in (v.get("buyer_id"), v.get("seller_id")):
            if uid in v.get("hidden_from", []):
                continue
                
            name = v.get("product", {}).get("name", "Chat")
            buttons.append([
                InlineKeyboardButton(f"💬 {name}", callback_data=f"chat:open:{k}"),
                InlineKeyboardButton("🗑", callback_data=f"chat:delete:{k}")
            ])

    buttons.append([InlineKeyboardButton("🏠 Home", callback_data="menu:main")])
    
    text = "💌 *Your Messages*\n" + "━" * 15
    kb = InlineKeyboardMarkup(buttons)
    
    # Handle both message and callback_query updates
    if update.callback_query:
        return await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        return await context.bot.send_message(uid, text, reply_markup=kb, parse_mode="Markdown")

# ==========================================
# File Order Disputes
# ==========================================

async def file_order_dispute(update, context, oid):
    q = update.callback_query
    uid = update.effective_user.id
    
    # Update the status in storage
    # This assumes your storage.update_order_status handles finding the order by ID
    success = storage.update_order_status(oid, "disputed")
    
    if success:
        await q.answer("⚖️ Dispute filed. An admin will review this order.", show_alert=True)
        # Notify Admin (Optional but recommended)
        try:
            await context.bot.send_message(
                ADMIN_ID, 
                f"⚠️ **NEW DISPUTE FILED**\nOrder ID: `{oid}`\nBy User: `{uid}`"
            )
        except:
            pass
    else:
        await q.answer("❌ Could not file dispute. Order not found.", show_alert=True)
    
    # Refresh the orders page
    return await on_menu(update, context, force_tab="orders")

# ==========================================
# FUNCTIONS PANEL
# ==========================================
async def show_functions_menu(update, context):
    q = update.callback_query

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Disputes (Admin)", callback_data="admin:disputes")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
    ])

    await q.edit_message_text(
        "⚙️ *Functions Panel*\nAdmin tools + utilities.",
        reply_markup=kb,
        parse_mode="Markdown",
    )

async def admin_open_disputes(update, context):
    q = update.callback_query
    uid = update.effective_user.id

    if uid != ADMIN_ID:
        return await q.answer("🚫 Access Denied", show_alert=True)

    # Load data
    all_orders_data = storage.load_json(storage.ORDERS_FILE)
    
    # FIX: Check if it's a dict. If so, iterate over the values (the actual order objects)
    if isinstance(all_orders_data, dict):
        all_orders = list(all_orders_data.values())
    else:
        all_orders = all_orders_data

    disputed = [o for o in all_orders if isinstance(o, dict) and o.get("status") in ["disputed", "escrow", "paid"]]

    if not disputed:
        return await q.edit_message_text(
            "⚖️ *Admin Dispute Panel*\n\n✅ No active disputes found.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="menu:main")]]),
            parse_mode="Markdown"
        )

    lines = ["⚖️ *Active Disputes/Escrow*"]
    buttons = []

    for o in disputed[:10]:
        oid = o.get('id', '???')
        amt = o.get('amount', 0)
        lines.append(f"\n📦 `ID: {oid}`\n💰 `${float(amt):.2f}` | 👤 Buyer: `{o.get('buyer_id')}`")
        
        buttons.append([
            InlineKeyboardButton(f"✅ Release {oid}", callback_data=f"admin_release:{oid}"),
            InlineKeyboardButton(f"💰 Refund {oid}", callback_data=f"admin_refund:{oid}")
        ])

    buttons.append([InlineKeyboardButton("🏠 Home", callback_data="menu:main")])

    await q.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

async def admin_release(update, context, oid):
    # Logic to finalize order and move funds to seller's balance
    success = storage.update_order_status(oid, "completed")
    if success:
        await update.callback_query.answer(f"✅ Order {oid} released to seller!", show_alert=True)
    else:
        await update.callback_query.answer("❌ Error updating order.", show_alert=True)
    return await admin_open_disputes(update, context)

async def admin_refund(update, context, oid):
    # 1. Update status to 'refunded'
    success = storage.update_order_status(oid, "refunded")
    
    if success:
        # 2. Logic to actually credit the buyer's balance should be inside 
        # storage.update_order_status or called here:
        # storage.adjust_balance(buyer_id, amount)
        
        await update.callback_query.answer(f"💰 Order {oid} refunded!", show_alert=True)
        
        # 3. Notify the Buyer automatically
        order_data = storage.get_order_by_id(oid) # Assuming you have this helper
        if order_data:
            try:
                await context.bot.send_message(
                    chat_id=order_data['buyer_id'],
                    text=f"⚖️ **Dispute Resolved**: Order `{oid}` has been refunded to your wallet."
                )
            except:
                pass
    else:
        await update.callback_query.answer("❌ Error: Order not found.", show_alert=True)
    
    return await admin_open_disputes(update, context)