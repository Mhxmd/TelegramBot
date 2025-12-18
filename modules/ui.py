VERCEL_PAY_URL = "https://fake-paynow-yourname.vercel.app"

import os
import qrcode
from io import BytesIO
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from typing import Optional
import stripe

from modules import storage, seller, chat, inventory, shopping_cart
import modules.wallet_utils as wallet

# Load .env
load_dotenv()
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
stripe.api_key = STRIPE_SECRET_KEY
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# ===========================
# BUILT-IN PRODUCTS
# ===========================
CATALOG = {
    "cat": {"name": "Cat Plush", "price": 15, "emoji": "🐱", "seller_id": 0, "desc": "Cute cat plush."},
    "hoodie": {"name": "Hoodie", "price": 30, "emoji": "🧥", "seller_id": 0, "desc": "Minimalist navy hoodie."},
    "blackcap": {"name": "Black Cap", "price": 12, "emoji": "🧢", "seller_id": 0, "desc": "Matte black cap."},
}

def clamp_qty(q): return max(1, min(int(q), 99))

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
# PAYNOW QR GENERATION
# ==========================================
def generate_paynow_qr(amount: float, item_name: str, order_id: Optional[str] = None):
    import time, random
    from urllib.parse import urlencode

    if order_id is None:
        order_id = f"O{int(time.time())}{random.randint(100,999)}"

    qs = urlencode({"order": order_id, "item": item_name, "amount": f"{amount:.2f}"})
    url = VERCEL_PAY_URL.rstrip("/") + "/?" + qs

    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    bio.url = url
    bio.order_id = order_id
    return bio


# ==========================================
# SEARCH
# ==========================================
def search_products_by_name(query: str):
    query = query.lower().strip()
    results = []
    for it in enumerate_all_products():
        if query in it.get("name", "").lower():
            results.append(it)
    return results


# ==========================================
# MAIN MENU
# ==========================================
def build_main_menu(balance: float):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Marketplace", callback_data="menu:shop"),
         InlineKeyboardButton("📦 Orders", callback_data="menu:orders")],
        [InlineKeyboardButton("🛒 Cart", callback_data="cart:view"),
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
def build_shop_keyboard():
    items = enumerate_all_products()

    rows = []
    display_lines = []

    for it in items:
        sku = it["sku"]
        price = it["price"]

        display_lines.append(f"{it.get('emoji','🛍')} *{it['name']}* — `${price:.2f}`")

        rows.append([
            InlineKeyboardButton(f"💰 Buy ${price:.2f}", callback_data=f"buy:{sku}:1"),
            InlineKeyboardButton("🛒 Add to Cart", callback_data=f"cart:add:{sku}"),
            InlineKeyboardButton("💬 Contact Seller", callback_data=f"contact:{sku}:{it.get('seller_id',0)}"),
        ])

    rows.append([InlineKeyboardButton("🔍 Search Items", callback_data="shop:search")])
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="menu:main")])

    txt = (
        "🛍 **Xchange Marketplace**\nBrowse products or list your own.\n\n"
        + ("\n".join(display_lines) if display_lines else "_No items yet._")
    )
    return txt, InlineKeyboardMarkup(rows)


# ==========================================
# CART CHECKOUT (ALL ITEMS)
# ==========================================
async def cart_checkout_all(update, context):
    q = update.callback_query
    uid = update.effective_user.id

    cart = shopping_cart.get_user_cart(uid)
    if not cart:
        return await q.answer("Your cart is empty.", show_alert=True)

    total = sum(item["price"] * item["qty"] for item in cart.values())

    txt = (
        "🧾 *Cart Checkout*\n\n"
        f"• Total: *${total:.2f}*\n\n"
        "_Choose payment method:_"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Stripe", callback_data=f"stripe_cart:{total}")],
        [InlineKeyboardButton("🇸🇬 PayNow", callback_data=f"paynow_cart:{total}")],
        [InlineKeyboardButton("🟦 NETS", callback_data=f"nets_cart:{total}")],
        [InlineKeyboardButton("🔙 Back", callback_data="cart:view")],
    ])

    return await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=kb)


# ==========================================
# PAYNOW (CART)
# ==========================================
async def show_paynow_cart(update, context, total):
    q = update.callback_query

    qr = generate_paynow_qr(float(total), "Cart Checkout")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I HAVE PAID", callback_data="cart:confirm_payment")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cart:view")],
    ])

    await q.message.reply_photo(
        photo=InputFile(qr, filename="paynow_cart.png"),
        caption=f"🇸🇬 *Demo PayNow — Cart*\nAmount: *${float(total):.2f}*",
        reply_markup=kb,
        parse_mode="Markdown",
    )


# ==========================================
# NETS QR (CART)
# ==========================================
async def show_nets_cart(update, context, total):
    from modules.nets_qr import generate_nets_qr

    q = update.callback_query
    qr_img, ref = await generate_nets_qr(float(total))

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I PAID (Simulate)", callback_data=f"payconfirm:{ref}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"paycancel:{ref}")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
    ])

    await q.message.reply_photo(
        photo=InputFile(qr_img, filename=f"nets_cart_{ref}.png"),
        caption=f"🟦 *NETS QR — Cart*\nTotal: *${total}*\nRef: `{ref}`",
        parse_mode="Markdown",
        reply_markup=kb,
    )


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

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Stripe", callback_data=f"stripe:{sku}:{qty}")],
        [InlineKeyboardButton("🇸🇬 PayNow", callback_data=f"paynow:{sku}:{qty}")],
        [InlineKeyboardButton("🟦 NETS", callback_data=f"nets:{sku}:{qty}")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu:shop")],
    ])

    txt = (
        f"{item.get('emoji')} *{item['name']}*\n"
        f"Qty: *{qty}*\nTotal: *${total:.2f}*"
    )

    await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=kb)


# ==========================================
# QUANTITY CHANGE SCREEN
# ==========================================
async def on_qty(update, context, sku, qty):
    q = update.callback_query
    item = get_any_product_by_sku(sku)
    qty = clamp_qty(qty)
    total = float(item["price"]) * qty

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("−", callback_data=f"qty:{sku}:{qty-1}"),
            InlineKeyboardButton(f"Qty: {qty}", callback_data="noop"),
            InlineKeyboardButton("+", callback_data=f"qty:{sku}:{qty+1}"),
        ],
        [InlineKeyboardButton("✅ Checkout", callback_data=f"checkout:{sku}:{qty}")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu:shop")],
    ])

    await q.edit_message_text(
        f"{item['name']} • Qty {qty}\nTotal ${total:.2f}",
        reply_markup=kb,
        parse_mode="Markdown",
    )


# ==========================================
# CHECKOUT → calls BUY screen again
# ==========================================
async def on_checkout(update, context, sku, qty):
    return await on_buy(update, context, sku, qty)


# ==========================================
# STRIPE — SINGLE ITEM
# ==========================================
async def create_stripe_checkout(update, context, sku, qty):
    import requests

    q = update.callback_query
    item = get_any_product_by_sku(sku)
    qty = clamp_qty(qty)
    total = float(item["price"]) * qty
    user_id = update.effective_user.id
    order_id = f"{sku}_{user_id}"

    try:
        res = requests.post(
            os.getenv("SERVER_BASE_URL") + "/create_checkout_session",
            json={
                "order_id": order_id,
                "amount": total,
                "user_id": user_id
            }
        ).json()
        checkout_url = res["checkout_url"]
    except Exception as e:
        return await q.edit_message_text(f"Error: {e}")

    storage.add_order(user_id, item["name"], qty, total, "Stripe", int(item.get("seller_id", 0)))

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pay Now", url=checkout_url)],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu:shop")],
    ])

    await q.edit_message_text(
        f"*Stripe Checkout*\nItem: {item['name']}\nQty: {qty}\nTotal: ${total:.2f}",
        reply_markup=kb,
        parse_mode="Markdown",
    )


# ==========================================
# PAYNOW — SINGLE ITEM
# ==========================================
async def show_paynow(update, context, sku, qty):
    q = update.callback_query
    item = get_any_product_by_sku(sku)
    qty = clamp_qty(qty)
    total = float(item["price"]) * qty

    qr = generate_paynow_qr(total, item["name"])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I HAVE PAID", callback_data=f"payconfirm:{qr.order_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"paycancel:{qr.order_id}")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
    ])

    await q.message.reply_photo(
        photo=InputFile(qr, filename="paynow_single.png"),
        caption=f"*Demo PayNow*\nItem: {item['name']}\nAmount: ${total:.2f}",
        parse_mode="Markdown",
        reply_markup=kb,
    )


# ==========================================
# NETS — SINGLE ITEM
# ==========================================
async def show_nets_qr(update, context, sku, qty):
    from modules.nets_qr import generate_nets_qr

    q = update.callback_query
    item = get_any_product_by_sku(sku)
    qty = clamp_qty(qty)
    total = float(item["price"]) * qty

    qr_img, ref = await generate_nets_qr(total)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I PAID (Simulate)", callback_data=f"payconfirm:{ref}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"paycancel:{ref}")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
    ])

    await q.message.reply_photo(
        photo=InputFile(qr_img, filename=f"nets_{ref}.png"),
        caption=f"NETS Payment\nAmount: ${total:.2f}\nRef: `{ref}`",
        parse_mode="Markdown",
        reply_markup=kb,
    )


# ==========================================
# MENU ROUTER
# ==========================================
async def on_menu(update, context):
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
        bal = storage.get_balance(uid)
        pub = wallet.ensure_user_wallet(uid)["public_key"]

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Deposit", callback_data="wallet:deposit")],
            [InlineKeyboardButton("📤 Withdraw", callback_data="wallet:withdraw")],
            [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
        ])

        return await safe_edit(
            f"💼 **Wallet**\n• Balance: `${bal:.2f}`\n• Solana: `{pub}`",
            kb,
        )

    if tab == "messages":
        threads = storage.load_json(storage.MESSAGES_FILE)
        buttons = [
            [InlineKeyboardButton(f"💬 {v['product']['name']}", callback_data=f"chat:open:{k}")]
            for k, v in threads.items()
            if uid in (v.get("buyer_id"), v.get("seller_id"))
        ]
        buttons.append([InlineKeyboardButton("🏠 Home", callback_data="menu:main")])

        return await safe_edit("💌 *Messages*", InlineKeyboardMarkup(buttons))
    
    if tab == "orders":
        orders = storage.list_orders_for_user(uid)

        if not orders:
            txt = "📦 *Orders*\n\nNo orders yet."
        else:
            orders = sorted(
                orders,
                key=lambda o: int(o.get("ts", 0)),
                reverse=True
            )

            lines = ["📦 *Orders*"]
            for o in orders[:20]:
                oid = o.get("id", "unknown")
                item = o.get("item", "item")
                qty = o.get("qty", 1)
                amt = float(o.get("amount", 0))
                status = o.get("status", "pending")
                method = o.get("method", "-")

                lines.append(f"\n• `{oid}`")
                lines.append(f"  {item} x{qty}  `${amt:.2f}`")
                lines.append(f"  Status: *{status}*  Method: {method}")

            txt = "\n".join(lines)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
        ])
        return await safe_edit(txt, kb)

    if tab == "sell":
        txt, kb = seller.build_seller_menu(storage.get_role(uid))
        return await safe_edit(txt, kb)

    if tab == "functions":
        return await show_functions_menu(update, context)

    if tab in ("main", "refresh"):
        kb, txt = build_main_menu(storage.get_balance(uid))
        return await safe_edit(txt, kb)


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
