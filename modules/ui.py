VERCEL_PAY_URL = "https://fake-paynow-yourname.vercel.app"


import stripe
import qrcode
from io import BytesIO
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from modules import storage, seller, chat
import modules.wallet_utils as wallet   # safe import

# Built-in product catalog
CATALOG = {
    "cat": {"name": "Cat Plush", "price": 15, "emoji": "🐱", "seller_id": 0, "desc": "Cute cat plush."},
    "hoodie": {"name": "Hoodie", "price": 30, "emoji": "🧥", "seller_id": 0, "desc": "Comfy cotton hoodie."},
    "blackcap": {"name": "Black Cap", "price": 12, "emoji": "🧢", "seller_id": 0, "desc": "Minimalist black cap."},
}

# ---------------- HELPERS ----------------
def clamp_qty(q):
    return max(1, min(int(q), 99))

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
        return CATALOG[sku]
    data = storage.load_json(storage.SELLER_PRODUCTS_FILE)
    for _, items in data.items():
        for it in items:
            if it["sku"] == sku:
                return it
    return None

def generate_dummy_payment_url(order_id: str, item_name: str, amount: float) -> str:
    """
    Builds the fake gateway URL with query params that the Vercel page will read.
    Example: https://fake-paynow-mu.vercel.app/?order=123&item=Cat&amount=15
    """
    from urllib.parse import urlencode
    qs = urlencode({"order": order_id, "item": item_name, "amount": f"{amount:.2f}"})
    return VERCEL_PAY_URL.rstrip("/") + "/?" + qs

def generate_paynow_qr(amount: float, item_name: str, order_id: str = None) -> BytesIO:
    """
    Create a QR image that points to the dummy payment page on Vercel.
    Returns BytesIO ready to be sent as InputFile.
    """
    if order_id is None:
        # make a short pseudo-random order id (timestamp + random)
        import time, random
        order_id = f"O{int(time.time())}{random.randint(100,999)}"

    url = generate_dummy_payment_url(order_id, item_name, amount)
    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    # attach metadata so caller can know order id / url if needed
    bio.order_id = order_id   # dynamic attribute for convenience
    bio.url = url
    return bio


# ---------------- MAIN MENU ----------------
def build_main_menu(balance: float):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍️ Shop", callback_data="menu:shop"),
         InlineKeyboardButton("📦 Orders", callback_data="menu:orders")],
        [InlineKeyboardButton("💼 Wallet", callback_data="menu:wallet"),
         InlineKeyboardButton("🛠 Sell", callback_data="menu:sell")],
        [InlineKeyboardButton("💬 Public Chat", callback_data="chat:public_open"),
         InlineKeyboardButton("✉️ Messages", callback_data="menu:messages")],
        [InlineKeyboardButton("⚙️ Functions", callback_data="menu:functions"),
         InlineKeyboardButton("🔄 Refresh", callback_data="menu:refresh")],
    ])
    txt = f"👋 *Welcome to Telegram Marketplace!*\n\n💰 Balance: *${balance:.2f}*\n—\nBrowse, sell & chat."
    return kb, txt


# ---------------- SHOP UI ----------------
def build_shop_keyboard():
    items = enumerate_all_products()
    rows, text_lines = [], []
    for it in items:
        text_lines.append(f"{it.get('emoji','🛒')} *{it['name']}* — ${it['price']:.2f}")
        rows.append([
            InlineKeyboardButton(f"Buy ${it['price']:.2f}", callback_data=f"buy:{it['sku']}:1"),
            InlineKeyboardButton("💬 Contact Seller", callback_data=f"contact:{it['sku']}:{it.get('seller_id',0)}")
        ])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])
    text = "🛍️ *Shop*\n\n" + "\n".join(text_lines) if text_lines else "No listings yet."
    return text, InlineKeyboardMarkup(rows)


# ---------------- PAYNOW / STRIPE ----------------
def generate_paynow_qr(amount: float, item_name: str, order_id: str = None) -> BytesIO:
    """
    Create a QR image pointing to fake PayNow gateway.
    """
    import time, random
    from urllib.parse import urlencode

    # Create order id if missing
    if order_id is None:
        order_id = f"O{int(time.time())}{random.randint(100,999)}"

    # build fake pay URL
    qs = urlencode({
        "order": order_id,
        "item": item_name,
        "amount": f"{amount:.2f}"
    })
    url = VERCEL_PAY_URL.rstrip("/") + "/?" + qs

    # make QR
    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)

    # Attach useful metadata
    bio.order_id = order_id
    bio.url = url
    return bio

async def create_stripe_checkout(update, context, sku, qty):
    item = get_any_product_by_sku(sku)
    if not item:
        return await update.callback_query.answer("Item missing", show_alert=True)

    qty = clamp_qty(qty)
    total = int(item["price"] * 100)

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": item["name"]},
                    "unit_amount": total,
                },
                "quantity": qty
            }],
            mode="payment",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )
    except Exception as e:
        return await update.callback_query.edit_message_text(f"Stripe error: `{e}`")

    storage.add_order(update.effective_user.id, item["name"], qty, item["price"] * qty, "Stripe", item["seller_id"])
    await update.callback_query.edit_message_text(
        f"💳 **Pay with Stripe**\nClick below:\n{session.url}", parse_mode="Markdown"
    )

import uuid

async def show_paynow(update, context, sku: str, qty: int):
    """
    Called when user chooses PayNow QR. Generates a dummy gateway link + QR and
    sends a nice message with buttons:
    - ✅ I HAVE PAID  -> buyer clicks after "pretend pay"
    - ❌ Cancel
    """
    q = update.callback_query
    user_id = update.effective_user.id

    # lookup item
    item = get_any_product_by_sku(sku)
    if not item:
        await q.answer("Item not found.", show_alert=True)
        return

    qty = clamp_qty(qty)
    total = float(item["price"]) * qty

    # create an order record (pending) and get a local order id
    # you probably already have add_order; reuse it to record order
    # We'll also create a unique order id for the fake gateway
    import time, random
    order_ref = f"ORD{int(time.time())}{random.randint(100,999)}"
    storage.add_order(user_id, item["name"], qty, total, "PayNow (fake)", int(item.get("seller_id", 0)))
    # (optionally, you might want to embed order_ref into stored order; adjust add_order if needed)

    # generate QR that points to the Vercel fake gateway
    qr = generate_paynow_qr(total, item["name"], order_ref)

    # buttons for the flow (I HAVE PAID should trigger an admin/process flow)
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

    # send QR as an image with caption + buttons
    try:
        await q.message.reply_photo(
            photo=InputFile(qr, filename=f"paynow_{order_ref}.png"),
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
    except Exception:
        # fallback: send url and buttons if sending image fails
        await q.edit_message_text(
            f"{caption}\n\nQR could not be sent; open the link instead: {qr.url}",
            reply_markup=kb,
            parse_mode=ParseMode.MARKDOWN
        )

    # done — later your callback_router should handle payconfirm: and paycancel:



# ---------------- MENU ROUTER ----------------
async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _, tab = q.data.split(":", 1)
    uid = update.effective_user.id

    if tab == "shop":
        txt, kb = build_shop_keyboard()
        return await q.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

    if tab == "wallet":
        bal = storage.get_balance(uid)
        pub = wallet.ensure_user_wallet(uid)["public_key"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Deposit", callback_data="wallet:deposit")],
            [InlineKeyboardButton("📤 Withdraw", callback_data="wallet:withdraw")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")],
        ])
        return await q.edit_message_text(
            f"💼 *Wallet*\nFiat: ${bal:.2f}\nSolana: `{pub}`\n", parse_mode="Markdown", reply_markup=kb
        )

    if tab == "messages":
        threads = storage.load_json(storage.MESSAGES_FILE)
        btns = [[InlineKeyboardButton(f"💬 {v['product']['name']}", callback_data=f"chat:open:{k}")]
                for k, v in threads.items() if uid in (v.get("buyer_id"), v.get("seller_id"))]
        btns.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])
        msg = "💌 *Your Chats*:\n" if len(btns) > 1 else "No chats yet."
        return await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(btns), parse_mode="Markdown")

    if tab == "sell":
        txt, kb = seller.build_seller_menu(storage.get_role(uid))
        return await q.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

    if tab in ("main", "refresh"):
        kb, txt = build_main_menu(storage.get_balance(uid))
        return await q.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
    
    # ===========================
# SHOP BUY / QTY / CHECKOUT
# ===========================

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
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_shop")]
    ])

    txt = (
        f"{item.get('emoji','🛒')} *{item['name']}*\n"
        f"Qty: {qty}\n"
        f"Total: *${total:.2f}*\n\n"
        "Choose a payment method:"
    )

    await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


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
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_shop")]
    ])

    txt = (
        f"{item.get('emoji','🛒')} *{item['name']}*\n"
        f"Price: ${item['price']:.2f}\n"
        f"Qty: {qty}\n"
        f"Total: *${total:.2f}*\n\n"
        "Adjust quantity or checkout:"
    )

    await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

async def show_post_payment_options(chat_id, context, order_id, seller_id):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 I Have Shipped", callback_data=f"ship:{order_id}")],
        [InlineKeyboardButton("✅ I Received My Item", callback_data=f"recv:{order_id}")],
        [InlineKeyboardButton("❗ Report Issue", callback_data=f"dispute:{order_id}")]
    ])

    await context.bot.send_message(
        chat_id,
        f"🛒 Order **{order_id}** is now in ESCROW.\n\n"
        f"Seller will ship your item.\nFunds are held securely.",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def on_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, qty: int):
    # Checkout simply returns to on_buy screen
    await on_buy(update, context, sku, qty)

# ===========================
# ESCROW PAY CONFIRM HANDLERS
# ===========================

async def handle_pay_confirm(update, context, order_id):
    from modules import storage
    q = update.callback_query
    
    # Update order status to escrow_hold
    storage.update_order_status(order_id, "escrow_hold")

    msg = (
        f"✅ *Payment Confirmed!*\n"
        f"Order `{order_id}` has been placed.\n"
        f"Funds are now held securely in escrow.\n\n"
        f"📦 Seller will ship your item soon."
    )

    # Attempt to edit message first (works when callback pressed inside Telegram)
    try:
        await q.edit_message_text(msg, parse_mode="Markdown")
    except:
        # If editing fails (like returning from Vercel), send a new message instead
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text=msg,
            parse_mode="Markdown"
        )


async def handle_pay_cancel(update, context, order_id):
    q = update.callback_query

    msg = "❌ Payment cancelled. Your order has been discarded."

    try:
        await q.edit_message_text(msg)
    except:
        await context.bot.send_message(update.effective_user.id, msg)


# ===========================
# ESCROW FLOW CONTINUATION
# ===========================

async def handle_mark_shipped(update, context, order_id):
    from modules import storage
    q = update.callback_query
    order = storage.get_order(order_id)

    storage.update_order_status(order_id, "shipped")

    # Notify buyer
    try:
        await context.bot.send_message(
            order["buyer_id"],
            f"📦 Your seller has marked order `{order_id}` as shipped!\n\nPlease confirm once received."
        )
    except:
        pass

    msg = f"✅ Order `{order_id}` marked as shipped."
    try:
        await q.edit_message_text(msg)
    except:
        await q.message.reply_text(msg)

async def handle_release_payment(update, context, order_id):
    from modules import storage
    q = update.callback_query
    order = storage.get_order(order_id)

    storage.update_order_status(order_id, "released")

    # Notify seller
    try:
        await context.bot.send_message(
            order["seller_id"],
            f"💰 Buyer confirmed receipt!\nPayment released for order `{order_id}` ✅"
        )
    except:
        pass

    msg = f"🎉 Payment released for order `{order_id}`!\nHope you enjoy your item!"
    try:
        await q.edit_message_text(msg)
    except:
        await q.message.reply_text(msg)

async def handle_dispute_case(update, context, order_id):
    from modules import storage
    q = update.callback_query
    order = storage.get_order(order_id)

    storage.update_order_status(order_id, "disputed")

    # Notify admins (Escrow team)
    ADMIN_ID = 123456789  # replace with your Telegram ID
    try:
        await context.bot.send_message(
            ADMIN_ID,
            f"🚨 DISPUTE OPENED\nOrder `{order_id}`\nBuyer: `{order['buyer_id']}`\nSeller: `{order['seller_id']}`"
        )
    except:
        pass

    msg = f"⚠️ Dispute opened for order `{order_id}`.\nAdmin will review."
    try:
        await q.edit_message_text(msg)
    except:
        await q.message.reply_text(msg)
