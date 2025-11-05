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

def generate_dummy_payment_qr(item_name, amount, order_id):
    # Public test payment URL (fake gateway page we will build)
    base_url = "https://faked-payment-demo.vercel.app/pay"

    pay_url = f"{base_url}?order={order_id}&item={item_name}&amount={amount}"

    # generate QR to that link
    img = qrcode.make(pay_url)
    bio = BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return bio, pay_url


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
def generate_paynow_qr(amount, name="MarketplaceBot"):
    qr_data = f"PayNow to {name} — Amount: ${amount:.2f}"
    img = qrcode.make(qr_data)
    bio = BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
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

async def show_paynow(update, context, sku, qty):
    item = get_any_product_by_sku(sku)
    qty = clamp_qty(qty)
    total = item["price"] * qty
    order_id = str(uuid.uuid4())[:8]  # fake short order id

    qr, pay_url = generate_dummy_payment_qr(item["name"], total, order_id)

    storage.add_order(update.effective_user.id, item["name"], qty, total, "PayNow (Demo)", item["seller_id"])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I've Paid", callback_data=f"paynow_sim_success:{item['name']}:{qty}:{order_id}")],
        [InlineKeyboardButton("🌐 Open Payment Page", url=pay_url)],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu:main")]
    ])

    await update.effective_message.reply_photo(
        InputFile(qr, filename="paynow_demo.png"),
        caption=(
            f"🇸🇬 *Demo PayNow Gateway*\n\n"
            f"Amount: *${total:.2f}*\n"
            f"Order ID: `{order_id}`\n\n"
            f"📷 Scan QR or tap button below to simulate payment\n"
            f"➡️ {pay_url}"
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )




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


async def on_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, qty: int):
    # Checkout simply returns to on_buy screen
    await on_buy(update, context, sku, qty)
