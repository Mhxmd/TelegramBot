"""
ui.py – FULL SQL UI Layer
Works with db.py (PostgreSQL only)
No JSON at all.
"""

import os
import stripe
import qrcode
from io import BytesIO
from urllib.parse import urlencode

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from modules import db


# =====================================
# STRIPE CONFIG
# =====================================

STRIPE_API_KEY = os.getenv("STRIPE_API_KEY") or os.getenv("STRIPE_SECRET_KEY")
if STRIPE_API_KEY:
    stripe.api_key = STRIPE_API_KEY

VERCEL_PAY_URL = "https://fake-paynow-yourname.vercel.app"


# =====================================
# PAYNOW GENERATOR (dummy Singapore QR)
# =====================================
def generate_paynow_qr(amount: float, order_id: int):
    url = VERCEL_PAY_URL + "?" + urlencode({
        "order": order_id,
        "amount": f"{amount:.2f}",
        "type": "paynow"
    })

    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return bio, url


# =====================================
# MAIN MENU
# =====================================

async def build_main_menu(uid: int):
    wallet = await db.get_or_create_wallet(uid)
    balance = float(wallet["balance"])

    user = await db.get_user(uid)
    role = user["role"]
    verified = user["verification_status"]

    text = (
        "👋 *Marketplace Dashboard*\n\n"
        f"💰 Balance: *${balance:.2f}*\n"
        f"🧩 Role: `{role}`\n"
        f"🔒 Verified: {'Yes' if verified else 'No'}\n"
    )

    rows = [
        [InlineKeyboardButton("🛍 Browse", callback_data="menu:shop")],
        [InlineKeyboardButton("🛒 Cart", callback_data="menu:cart")],
        [InlineKeyboardButton("💼 Wallet", callback_data="menu:wallet")],
    ]

    if role == "seller":
        rows.append([InlineKeyboardButton("📦 My Products", callback_data="seller:products")])
        rows.append([InlineKeyboardButton("➕ Add Product", callback_data="seller:add")])

    rows.append([InlineKeyboardButton("📬 Orders", callback_data="menu:orders")])

    kb = InlineKeyboardMarkup(rows)
    return text, kb


# =====================================
# MENU ROUTER
# =====================================

async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _, tab = q.data.split(":", 1)
    uid = update.effective_user.id

    if tab == "main":
        text, kb = await build_main_menu(uid)

    elif tab == "shop":
        text, kb = await build_shop()

    elif tab == "cart":
        text, kb = await build_cart(uid)

    elif tab == "wallet":
        text, kb = await build_wallet(uid)

    elif tab == "orders":
        text, kb = await build_orders(uid)

    else:
        text = "❌ Unknown menu"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]])

    try:
        await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    except:
        await q.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


# =====================================
# SHOP VIEW
# =====================================

async def build_shop():
    items = await db.list_products()
    lines = []
    rows = []

    for p in items:
        pid = p["product_id"]
        price = float(p["price"])
        lines.append(f"• *{p['title']}* — ${price:.2f}")

        rows.append([
            InlineKeyboardButton(f"View", callback_data=f"product:view:{pid}"),
            InlineKeyboardButton("🛒 Add", callback_data=f"cart:add:{pid}"),
        ])

    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])

    txt = "🛍 *Shop*\n\n" + ("\n".join(lines) if lines else "_No items yet_")
    return txt, InlineKeyboardMarkup(rows)


# =====================================
# PRODUCT PAGE
# =====================================

async def show_product(update, context, pid: int):
    q = update.callback_query
    product, images = await db.get_product(pid)

    if not product:
        return await q.answer("Item not found", show_alert=True)

    txt = (
        f"🧺 *{product['title']}*\n\n"
        f"{product['description']}\n\n"
        f"💵 Price: *${float(product['price']):.2f}*\n"
        f"📦 Stock: {product['stock_quantity']}\n"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Add to Cart", callback_data=f"cart:add:{pid}")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu:shop")]
    ])

    if len(images) == 0:
        return await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=kb)

    # Show product image
    img = images[0]["image_url"]
    await q.message.reply_photo(img, caption=txt, parse_mode="Markdown", reply_markup=kb)


# =====================================
# CART VIEW + ACTIONS
# =====================================

async def build_cart(uid: int):
    items = await db.cart_get(uid)

    if not items:
        return (
            "🛒 *Your cart is empty.*",
            InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]])
        )

    lines = []
    rows = []

    for it in items:
        pid = it["product_id"]
        qty = it["quantity"]
        price = float(it["price"])
        subtotal = qty * price

        lines.append(f"• *{it['title']}* ×{qty} — ${subtotal:.2f}")

        rows.append([
            InlineKeyboardButton("➖", callback_data=f"cart:dec:{pid}"),
            InlineKeyboardButton(f"{qty}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"cart:inc:{pid}")
        ])
        rows.append([
            InlineKeyboardButton("❌ Remove", callback_data=f"cart:remove:{pid}")
        ])

    rows.append([InlineKeyboardButton("💳 Checkout", callback_data="cart:checkout")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])

    txt = "🛒 *Your Cart*\n\n" + "\n".join(lines)
    return txt, InlineKeyboardMarkup(rows)


async def cart_handler(update, context, action, pid=None):
    uid = update.effective_user.id

    if action == "add":
        await db.cart_add(uid, int(pid), 1)

    elif action == "inc":
        await db.cart_add(uid, int(pid), 1)

    elif action == "dec":
        await db.cart_add(uid, int(pid), -1)

    elif action == "remove":
        await db.cart_remove(uid, int(pid))

    text, kb = await build_cart(uid)
    q = update.callback_query
    await q.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)


# =====================================
# CHECKOUT FLOW
# =====================================

async def cart_checkout(update, context):
    q = update.callback_query
    uid = update.effective_user.id

    items = await db.cart_get(uid)
    if not items:
        return await q.answer("Your cart is empty", show_alert=True)

    rows = []
    total = 0

    for it in items:
        total += float(it["price"]) * it["quantity"]

    txt = (
        "💳 *Checkout*\n"
        f"Total: *${total:.2f}*\n\n"
        "Choose payment method:"
    )

    rows.append([InlineKeyboardButton("🇸🇬 PayNow", callback_data="pay:paynow")])
    rows.append([InlineKeyboardButton("💳 Stripe", callback_data="pay:stripe")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])

    await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))


# =====================================
# PAYNOW
# =====================================

async def paynow_checkout(update, context):
    q = update.callback_query
    uid = update.effective_user.id
    items = await db.cart_get(uid)

    total = sum(float(i["price"]) * i["quantity"] for i in items)

    qr, payload = generate_paynow_qr(total, order_id=99999)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I HAVE PAID", callback_data="pay:confirm")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")],
    ])

    await q.message.reply_photo(
        photo=InputFile(qr, filename="paynow.png"),
        caption=f"🇸🇬 *PayNow*\nAmount: *${total:.2f}*\nPayload:\n`{payload}`",
        parse_mode="Markdown",
        reply_markup=kb
    )


# =====================================
# STRIPE CHECKOUT
# =====================================

async def stripe_checkout(update, context):
    q = update.callback_query
    uid = update.effective_user.id
    items = await db.cart_get(uid)

    total = sum(float(i["price"]) * i["quantity"] for i in items)
    total_cents = int(total * 100)

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "quantity": 1,
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Marketplace purchase"},
                    "unit_amount": total_cents,
                }
            }],
            mode="payment",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )
    except Exception as e:
        return await q.edit_message_text(f"Stripe Error: `{e}`", parse_mode="Markdown")

    txt = f"💳 *Stripe Payment*\nClick link below:\n{session.url}"
    await q.edit_message_text(txt, parse_mode="Markdown")


# =====================================
# ORDERS
# =====================================

async def build_orders(uid: int):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM orders 
            WHERE buyer_id=$1 OR seller_id=$1
            ORDER BY order_id DESC
        """, uid)

    if not rows:
        return "📦 No orders yet.", InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
        ])

    lines = []
    for o in rows:
        lines.append(
            f"• Order `{o['order_id']}` — Status: *{o['order_status']}* — ${o['amount']:.2f}"
        )

    txt = "📦 *Your Orders*\n\n" + "\n".join(lines)

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]])
    return txt, kb


# =====================================
# WALLET
# =====================================

async def build_wallet(uid: int):
    wallet = await db.get_or_create_wallet(uid)
    text = (
        f"💼 *Wallet*\n"
        f"Balance: *${float(wallet['balance']):.2f}*\n"
        f"Solana Address:\n`{wallet['solana_address']}`"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
    ])

    return text, kb
