# modules/ui.py
# Adds: 🛒 Cart (persistent JSON), 🔍 Search, 🎚 Filters
# Works with your existing escrow, PayNow QR, Stripe, chat & dispute flows.

VERCEL_PAY_URL = "https://fake-paynow-yourname.vercel.app"

import os
import stripe
import qrcode
from io import BytesIO
from urllib.parse import urlencode
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from modules import storage, seller, chat
import modules.wallet_utils as wallet   # safe import

# ---------------- Built-in product catalog ----------------
CATALOG = {
    "cat": {"name": "Cat Plush", "price": 15, "emoji": "🐱", "seller_id": 0, "desc": "Cute cat plush."},
    "hoodie": {"name": "Hoodie", "price": 30, "emoji": "🧥", "seller_id": 0, "desc": "Comfy cotton hoodie."},
    "blackcap": {"name": "Black Cap", "price": 12, "emoji": "🧢", "seller_id": 0, "desc": "Minimalist black cap."},
}

# ---------------- Helpers ----------------
def clamp_qty(q):
    try:
        return max(1, min(int(q), 99))
    except Exception:
        return 1

def enumerate_all_products():
    items = []
    for sku, p in CATALOG.items():
        items.append({**p, "sku": sku})
    data = storage.load_json(storage.SELLER_PRODUCTS_FILE)
    for sid, plist in data.items():
        for it in plist:
            items.append(it)
    return items

def get_any_product_by_sku(sku: str):
    if sku in CATALOG:
        return {**CATALOG[sku], "sku": sku}
    data = storage.load_json(storage.SELLER_PRODUCTS_FILE)
    for _, items in data.items():
        for it in items:
            if it["sku"] == sku:
                return it
    return None

def generate_dummy_payment_url(order_id: str, item_name: str, amount: float) -> str:
    qs = urlencode({"order": order_id, "item": item_name, "amount": f"{amount:.2f}"})
    return VERCEL_PAY_URL.rstrip("/") + "/?" + qs

def generate_paynow_qr(amount: float, item_name: str, order_id: str = None) -> BytesIO:
    import time, random
    if order_id is None:
        order_id = f"O{int(time.time())}{random.randint(100,999)}"
    url = generate_dummy_payment_url(order_id, item_name, amount)
    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    bio.order_id = order_id
    bio.url = url
    return bio

# ---------------- Main Menu ----------------
def build_main_menu(balance: float):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍️ Shop", callback_data="menu:shop")],
        [InlineKeyboardButton("🛒 Cart", callback_data="cart:view")],
        [InlineKeyboardButton("💼 Wallet", callback_data="menu:wallet")],
        [InlineKeyboardButton("👤 Sell", callback_data="menu:sell")],
        [InlineKeyboardButton("🔧 More", callback_data="menu:more")],
    ])

    txt = (
        "👋 *Welcome to Telegram Marketplace!*\n\n"
        f"💰 Balance: *${balance:.2f}*\n"
        "—\n"
        "Browse, sell, search & chat."
    )
    return kb, txt


# ---------------- Shop UI ----------------
def _render_items_list(items):
    rows, lines = [], []
    for it in items:
        price = float(it["price"])
        sku = it["sku"]
        lines.append(f"{it.get('emoji','🛒')} *{it['name']}* — ${price:.2f}")
        rows.append([
            InlineKeyboardButton(f"Buy ${price:.2f}", callback_data=f"buy:{sku}:1"),
            InlineKeyboardButton("🛒 Add", callback_data=f"cart:add:{sku}:1"),
            InlineKeyboardButton("💬 Seller", callback_data=f"contact:{sku}:{it.get('seller_id',0)}"),
        ])
    return lines, rows

def build_shop_keyboard(filtered_items=None):
    items = filtered_items if filtered_items is not None else enumerate_all_products()
    lines, rows = _render_items_list(items)
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main"),
                 InlineKeyboardButton("🛒 View Cart", callback_data="cart:view")])
    text = "🛍️ *Shop*\n\n" + ("\n".join(lines) if lines else "_No listings yet._")
    return text, InlineKeyboardMarkup(rows)

# ---------------- Search ----------------
def build_search_menu():
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Type a query", callback_data="search:ask")],
        [InlineKeyboardButton("🧹 Clear", callback_data="search:clear")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
    ])
    return "🔍 *Search*\nSend any keywords to find matching products.", kb

def perform_search(query: str):
    q = (query or "").strip().lower()
    if not q:
        return []
    items = enumerate_all_products()
    result = []
    for it in items:
        hay = f"{it.get('name','')} {it.get('desc','')}".lower()
        if q in hay:
            result.append(it)
    return result

# ---------------- Filters ----------------
FILTER_PRESETS = [
    ("≤ $20", "price:0:20"),
    ("$20 – $50", "price:20:50"),
    ("> $50", "price:50:999999"),
    ("Built-in Only", "seller:builtin"),
    ("User Sellers Only", "seller:user"),
]

def build_filter_menu():
    rows = [[InlineKeyboardButton(label, callback_data=f"filter:apply:{code}")]
            for (label, code) in FILTER_PRESETS]
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main"),
                 InlineKeyboardButton("🛍️ Shop", callback_data="menu:shop")])
    kb = InlineKeyboardMarkup(rows)
    return "🎚 *Filters*\nPick a quick filter:", kb

def apply_filter(code: str):
    items = enumerate_all_products()
    if code.startswith("price:"):
        _, lo, hi = code.split(":")
        lo, hi = float(lo), float(hi)
        return [it for it in items if lo <= float(it["price"]) <= hi]
    if code == "seller:builtin":
        return [it for it in items if int(it.get("seller_id", 0)) == 0]
    if code == "seller:user":
        return [it for it in items if int(it.get("seller_id", 0)) != 0]
    return items

# ---------------- Cart (Persistent JSON) ----------------
def _cart_line(name, qty, price):
    return f"• {name} ×{qty} — ${price*qty:.2f}"

def build_cart_view(user_id: int):
    cart = storage.get_cart(user_id)  # dict sku -> qty
    if not cart:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛍️ Go Shop", callback_data="menu:shop")],
                                   [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]])
        return "🛒 *Your Cart*\n\n_Empty._", kb

    lines = []
    rows = []
    total = 0.0
    for sku, qty in cart.items():
        it = get_any_product_by_sku(sku)
        if not it:
            continue
        price = float(it["price"])
        total += price * qty
        lines.append(_cart_line(it["name"], qty, price))
        rows.append([
            InlineKeyboardButton("−", callback_data=f"cart:dec:{sku}"),
            InlineKeyboardButton(f"{qty}", callback_data="noop"),
            InlineKeyboardButton("+", callback_data=f"cart:inc:{sku}"),
            InlineKeyboardButton("❌", callback_data=f"cart:remove:{sku}"),
            InlineKeyboardButton("Checkout", callback_data=f"cart:checkout_one:{sku}"),
        ])

    rows.append([InlineKeyboardButton("🧹 Clear Cart", callback_data="cart:clear")])
    rows.append([InlineKeyboardButton("✅ Checkout All (each)", callback_data="cart:checkout_all")])
    rows.append([InlineKeyboardButton("🛍️ Shop", callback_data="menu:shop"),
                 InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])

    text = "🛒 *Your Cart*\n\n" + "\n".join(lines) + f"\n\n*Subtotal:* ${total:.2f}"
    return text, InlineKeyboardMarkup(rows)

# ---------------- PayNow / Stripe (reuse per-item flow) ----------------
async def create_stripe_checkout(update, context, sku, qty):
    item = get_any_product_by_sku(sku)
    if not item:
        return await update.callback_query.answer("Item missing", show_alert=True)

    qty = clamp_qty(qty)
    total_cents = int(float(item["price"]) * 100)

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": item["name"]},
                    "unit_amount": total_cents,
                },
                "quantity": qty
            }],
            mode="payment",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )
    except Exception as e:
        return await update.callback_query.edit_message_text(f"Stripe error: `{e}`")

    storage.add_order(update.effective_user.id, item["name"], qty, float(item["price"]) * qty, "Stripe", int(item.get("seller_id", 0)))
    await update.callback_query.edit_message_text(
        f"💳 **Pay with Stripe**\nClick below:\n{session.url}", parse_mode="Markdown"
    )

async def show_paynow(update, context, sku: str, qty: int):
    q = update.callback_query
    user_id = update.effective_user.id
    item = get_any_product_by_sku(sku)
    if not item:
        await q.answer("Item not found.", show_alert=True)
        return

    qty = clamp_qty(qty)
    total = float(item["price"]) * qty

    import time, random
    order_ref = f"ORD{int(time.time())}{random.randint(100,999)}"
    storage.add_order(user_id, item["name"], qty, total, "PayNow (fake)", int(item.get("seller_id", 0)))

    qr = generate_paynow_qr(total, item["name"], order_ref)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I HAVE PAID", callback_data=f"payconfirm:{order_ref}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"paycancel:{order_ref}")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")],
    ])

    caption = (
        f"🇸🇬 *FAKE PayNow — Test Mode*\n\n"
        f"*Item:* {item['name']}\n"
        f"*Qty:* {qty}\n"
        f"*Amount:* ${total:.2f}\n\n"
        f"Scan the QR or open: `{qr.url}`\n\n"
        "This is a demo gateway — click *I HAVE PAID* after you 'pretend pay'."
    )

    # Use reply_photo to avoid replacing shop text; allows safe return
    await q.message.reply_photo(
        photo=InputFile(qr, filename=f"paynow_{order_ref}.png"),
        caption=caption,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

# ---------------- Menu Router ----------------
async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _, tab = q.data.split(":", 1)
    uid = update.effective_user.id

    # Default fallback content — prevents "kb not defined" errors
    text = "🚫 Unknown menu."
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]])

    # -------------------------------
    # MAIN MENU
    # -------------------------------
    if tab == "main":
        bal = storage.get_balance(uid)
        kb, text = build_main_menu(bal)

    # -------------------------------
    # SHOP
    # -------------------------------
    elif tab == "shop":
        text, kb = build_shop_keyboard()

    # -------------------------------
    # WALLET
    # -------------------------------
    elif tab == "wallet":
        bal = storage.get_balance(uid)
        pub = wallet.ensure_user_wallet(uid)["public_key"]
        text = f"💼 *Wallet*\nFiat: ${bal:.2f}\nSolana: `{pub}`"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Deposit", callback_data="wallet:deposit")],
            [InlineKeyboardButton("📤 Withdraw", callback_data="wallet:withdraw")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")],
        ])

    # -------------------------------
    # SELLER MENU
    # -------------------------------
    elif tab == "sell":
        text, kb = seller.build_seller_menu(storage.get_role(uid))

    # -------------------------------
    # MESSAGES
    # -------------------------------
    elif tab == "messages":
        threads = storage.load_json(storage.MESSAGES_FILE)
        buttons = []
        for tid, t in threads.items():
            if uid in (t.get("buyer_id"), t.get("seller_id")):
                buttons.append([
                    InlineKeyboardButton(
                        f"💬 {t['product']['name']}",
                        callback_data=f"chat:open:{tid}"
                    )
                ])
        buttons.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])
        text = "✉️ *Your Messages*" if len(buttons) > 1 else "No chats yet."
        kb = InlineKeyboardMarkup(buttons)

    # -------------------------------
    # ORDERS
    # -------------------------------
    elif tab == "orders":
        text, kb = ui.build_orders_menu(uid)

    # -------------------------------
    # MORE MENU
    # -------------------------------
    elif tab == "more":
        text = "🔧 *More Options*"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📦 Orders", callback_data="menu:orders")],
            [InlineKeyboardButton("🔍 Search", callback_data="search:menu")],
            [InlineKeyboardButton("🎯 Filter", callback_data="filter:menu")],
            [InlineKeyboardButton("✉️ Messages", callback_data="menu:messages")],
            [InlineKeyboardButton("💬 Public Chat", callback_data="chat:public_open")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")],
        ])

    # -------------------------------
    # SAFE EDIT (works with photos OR text)
    # -------------------------------
    try:
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        try:
            await q.edit_message_caption(text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            await context.bot.send_message(
                chat_id=uid,
                text=text,
                reply_markup=kb,
                parse_mode="Markdown"
            )

# ---------------- Buy / Qty ----------------
async def on_buy(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, qty: int):
    q = update.callback_query
    item = get_any_product_by_sku(sku)
    if not item:
        return await q.answer("Item not found.", show_alert=True)

    qty = clamp_qty(qty)
    total = float(item["price"]) * qty

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pay with Stripe", callback_data=f"stripe:{sku}:{qty}")],
        [InlineKeyboardButton("🇸🇬 PayNow QR", callback_data=f"paynow:{sku}:{qty}")],
        [InlineKeyboardButton("🛒 Add to Cart", callback_data=f"cart:add:{sku}:{qty}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_shop")]
    ])

    txt = (
        f"{item.get('emoji','🛒')} *{item['name']}*\n"
        f"Qty: {qty}\n"
        f"Total: *${total:.2f}*\n\n"
        "Choose a payment method or add to cart:"
    )
    try:
        await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    except Exception:
        await context.bot.send_message(chat_id=update.effective_user.id, text=txt, reply_markup=kb, parse_mode="Markdown")

async def on_qty(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, qty: int):
    q = update.callback_query
    item = get_any_product_by_sku(sku)
    if not item:
        return await q.answer("Item not found.", show_alert=True)

    qty = clamp_qty(qty)
    total = float(item["price"]) * qty

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("−", callback_data=f"qty:{sku}:{qty-1}"),
            InlineKeyboardButton(f"Qty: {qty}", callback_data="noop"),
            InlineKeyboardButton("+", callback_data=f"qty:{sku}:{qty+1}")
        ],
        [InlineKeyboardButton("✅ Checkout", callback_data=f"checkout:{sku}:{qty}")],
        [InlineKeyboardButton("🛒 Add to Cart", callback_data=f"cart:add:{sku}:{qty}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_shop")]
    ])

    txt = (
        f"{item.get('emoji','🛒')} *{item['name']}*\n"
        f"Price: ${item['price']:.2f}\n"
        f"Qty: {qty}\n"
        f"Total: *${total:.2f}*\n\n"
        "Adjust quantity / checkout / add to cart:"
    )
    try:
        await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    except Exception:
        await context.bot.send_message(chat_id=update.effective_user.id, text=txt, reply_markup=kb, parse_mode="Markdown")

async def on_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, qty: int):
    await on_buy(update, context, sku, qty)

# ---------------- Cart Handlers ----------------
async def cart_add(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, qty: int):
    q = update.callback_query
    uid = update.effective_user.id
    qty = clamp_qty(qty)
    it = get_any_product_by_sku(sku)
    if not it:
        return await q.answer("Item not found.", show_alert=True)
    storage.cart_add(uid, sku, qty)
    await q.answer("Added to cart 🛒")
    # show cart preview
    txt, kb = build_cart_view(uid)
    try:
        await q.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await context.bot.send_message(chat_id=uid, text=txt, reply_markup=kb, parse_mode="Markdown")

async def cart_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    txt, kb = build_cart_view(uid)
    try:
        await q.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await context.bot.send_message(chat_id=uid, text=txt, reply_markup=kb, parse_mode="Markdown")

async def cart_inc(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str):
    uid = update.effective_user.id
    storage.cart_change(uid, sku, +1)
    await cart_view(update, context)

async def cart_dec(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str):
    uid = update.effective_user.id
    storage.cart_change(uid, sku, -1)
    await cart_view(update, context)

async def cart_remove(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str):
    uid = update.effective_user.id
    storage.cart_remove(uid, sku)
    await cart_view(update, context)

async def cart_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    storage.cart_clear(uid)
    await cart_view(update, context)

async def cart_checkout_one(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str):
    # look up current qty from cart and open normal Buy UI (stripe/paynow)
    uid = update.effective_user.id
    cart = storage.get_cart(uid)
    qty = clamp_qty(cart.get(sku, 1))
    await on_buy(update, context, sku, qty)

async def cart_checkout_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Simple approach: show a list of per-item checkout buttons.
    (Keeps your existing per-item escrow & PayNow flow untouched.)
    """
    q = update.callback_query
    uid = update.effective_user.id
    cart = storage.get_cart(uid)
    if not cart:
        return await cart_view(update, context)

    rows = []
    lines = []
    for sku, qty in cart.items():
        it = get_any_product_by_sku(sku)
        if not it:
            continue
        lines.append(f"• {it['name']} ×{qty}")
        rows.append([InlineKeyboardButton(f"Checkout {it['name']}", callback_data=f"cart:checkout_one:{sku}")])

    rows.append([InlineKeyboardButton("🛍️ Shop", callback_data="menu:shop"),
                 InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])

    txt = "🧾 *Checkout All*\nChoose which to pay now:\n\n" + "\n".join(lines)
    kb = InlineKeyboardMarkup(rows)
    try:
        await q.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        await context.bot.send_message(chat_id=uid, text=txt, reply_markup=kb, parse_mode="Markdown")

# ---------------- ESCROW handlers (unchanged) ----------------
async def handle_pay_confirm(update, context, order_id):
    q = update.callback_query
    storage.update_order_status(order_id, "escrow_hold")
    msg = (
        f"✅ *Payment Confirmed!*\n"
        f"Order `{order_id}` has been placed.\n"
        f"Funds are now held securely in escrow.\n\n"
        f"📦 Seller will ship your item soon."
    )
    try:
        await q.edit_message_text(msg, parse_mode="Markdown")
    except Exception:
        await context.bot.send_message(chat_id=update.effective_user.id, text=msg, parse_mode="Markdown")

async def handle_pay_cancel(update, context, order_id):
    q = update.callback_query
    msg = "❌ Payment cancelled. Your order has been discarded."
    try:
        await q.edit_message_text(msg)
    except Exception:
        await context.bot.send_message(update.effective_user.id, msg)

# Admin/disputes helpers (same as your last version)
async def handle_mark_shipped(update, context, order_id):
    q = update.callback_query
    order = storage.get_order(order_id)
    storage.update_order_status(order_id, "shipped")
    try:
        await context.bot.send_message(order["buyer_id"], f"📦 Your seller marked order `{order_id}` as shipped!")
    except Exception:
        pass
    try:
        await q.edit_message_text(f"✅ Order `{order_id}` marked as shipped.")
    except Exception:
        await q.message.reply_text(f"✅ Order `{order_id}` marked as shipped.")

async def handle_release_payment(update, context, order_id):
    q = update.callback_query
    order = storage.get_order(order_id)
    storage.update_order_status(order_id, "released")
    try:
        await context.bot.send_message(order["seller_id"], f"💰 Buyer confirmed receipt — payment released for `{order_id}`.")
    except Exception:
        pass
    try:
        await q.edit_message_text(f"🎉 Payment released for `{order_id}`!")
    except Exception:
        await q.message.reply_text(f"🎉 Payment released for `{order_id}`!")

async def handle_dispute_case(update, context, order_id):
    q = update.callback_query
    order = storage.get_order(order_id)
    storage.update_order_status(order_id, "disputed")
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
    if ADMIN_ID:
        try:
            await context.bot.send_message(ADMIN_ID, f"🚨 DISPUTE OPENED\nOrder `{order_id}`\nBuyer: `{order['buyer_id']}`\nSeller: `{order['seller_id']}`")
        except Exception:
            pass
    try:
        await q.edit_message_text(f"⚠️ Dispute opened for `{order_id}`. Admin will review.")
    except Exception:
        await q.message.reply_text(f"⚠️ Dispute opened for `{order_id}`. Admin will review.")

# Admin panel
async def admin_open_disputes(update, context):
    q = update.callback_query
    uid = update.effective_user.id
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
    if uid != ADMIN_ID:
        return await q.answer("🚫 Admin Only")

    disputes = storage.get_all_disputed_orders()
    if not disputes:
        return await q.edit_message_text(
            "✅ No active disputes",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]])
        )

    text = "⚠️ *Active Disputes*\n\n"
    buttons = []
    for oid, o in disputes.items():
        text += f"• {o['item']} — ${o['amount']:.2f}\n"
        text += f"Buyer: `{o['buyer_id']}` | Seller: `{o['seller_id']}`\n"
        text += f"Status: `{o['status']}`\n\n"
        buttons.append([
            InlineKeyboardButton("✅ Refund Buyer", callback_data=f"admin_refund:{oid}"),
            InlineKeyboardButton("💰 Pay Seller", callback_data=f"admin_release:{oid}")
        ])
    buttons.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])

    await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def admin_refund(update, context, order_id):
    q = update.callback_query
    storage.update_order_status(order_id, "cancelled")
    o = storage.get_order(order_id)
    storage.update_balance(o["buyer_id"], o["amount"])
    await context.bot.send_message(o["buyer_id"], f"✅ Admin refunded your purchase of *{o['item']}*")
    await context.bot.send_message(o["seller_id"], f"⚠️ Buyer refunded for *{o['item']}*")
    await q.edit_message_text("✅ Buyer refunded, order cancelled",
                              parse_mode=ParseMode.MARKDOWN,
                              reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]]))

async def admin_release(update, context, order_id):
    q = update.callback_query
    storage.update_order_status(order_id, "released")
    o = storage.get_order(order_id)
    storage.update_balance(o["seller_id"], o["amount"])
    await context.bot.send_message(o["buyer_id"], f"⚠️ Admin released funds to seller for *{o['item']}*")
    await context.bot.send_message(o["seller_id"], f"💰 Funds released to you for *{o['item']}*")
    await q.edit_message_text("💰 Seller paid",
                              parse_mode=ParseMode.MARKDOWN,
                              reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]]))
