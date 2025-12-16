VERCEL_PAY_URL = "https://fake-paynow-yourname.vercel.app"

import os
from turtle import update
import qrcode
from io import BytesIO
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from modules import storage, seller, chat, inventory
from modules import shopping_cart
import modules.wallet_utils as wallet   # safe import

import stripe

# Load .env file from the project root
load_dotenv()

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
stripe.api_key = STRIPE_SECRET_KEY

ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Built-in product catalog
CATALOG = {
    "cat": {
        "name": "Cat Plush",
        "price": 15,
        "emoji": "🐱",
        "seller_id": 0,
        "desc": "Cute cat plush.",
    },
    "hoodie": {
        "name": "Hoodie",
        "price": 30,
        "emoji": "🧥",
        "seller_id": 0,
        "desc": "Minimalist navy hoodie.",
    },
    "blackcap": {
        "name": "Black Cap",
        "price": 12,
        "emoji": "🧢",
        "seller_id": 0,
        "desc": "Matte black cap.",
    },
}

# ---------------- HELPERS ----------------
def clamp_qty(q: int) -> int:
    """Clamp quantity between 1 and 99."""
    return max(1, min(int(q), 99))


def enumerate_all_products():
    """Built-in catalog + dynamic seller listings."""
    items = []
    for sku, p in CATALOG.items():
        items.append({**p, "sku": sku})
    data = storage.load_json(storage.SELLER_PRODUCTS_FILE)
    for _, plist in data.items():
        for it in plist:
            items.append(it)
    return items


def get_any_product_by_sku(sku: str):
    """Look up product from built-in catalog or seller listings."""
    if sku in CATALOG:
        return CATALOG[sku]
    data = storage.load_json(storage.SELLER_PRODUCTS_FILE)
    for _, items in data.items():
        for it in items:
            if it.get("sku") == sku:
                return it
    return None


def generate_paynow_qr(amount: float, item_name: str, order_id: str | None = None) -> BytesIO:
    """
    Create a QR image pointing to a fake PayNow gateway page hosted on Vercel.
    Encodes: https://fake-paynow.../?order=...&item=...&amount=...
    """
    import time, random
    from urllib.parse import urlencode

    if order_id is None:
        order_id = f"O{int(time.time())}{random.randint(100,999)}"

    qs = urlencode({
        "order": order_id,
        "item": item_name,
        "amount": f"{amount:.2f}",
    })
    url = VERCEL_PAY_URL.rstrip("/") + "/?" + qs

    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    # Attach metadata for callers
    bio.order_id = order_id  # type: ignore[attr-defined]
    bio.url = url            # type: ignore[attr-defined]
    return bio


# ---------------- SEARCH LOGIC ----------------
def search_products_by_name(query: str):
    query = query.lower().strip()
    results = []
    for it in enumerate_all_products():
        name = it.get("name", "").lower()
        if query in name:
            results.append(it)
    return results


# ---------------- MAIN MENU ----------------
def build_main_menu(balance: float):
    """
    Xchange — (Home Dashboard)
    """
    card = f"💳 *Balance:* `${balance:.2f}`"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🛍 Marketplace", callback_data="menu:shop"),
            InlineKeyboardButton("📦 Orders", callback_data="menu:orders"),
        ],
        [
            InlineKeyboardButton("🛒 Cart", callback_data="cart:view"),
            InlineKeyboardButton("💼 Wallet", callback_data="menu:wallet"),
        ],
        [
            InlineKeyboardButton("🛠 Sell", callback_data="menu:sell"),
            InlineKeyboardButton("✉ Messages", callback_data="menu:messages"),
        ],
        [
            InlineKeyboardButton("💬 Lounge", callback_data="chat:public_open"),
            InlineKeyboardButton("⚙ Functions", callback_data="menu:functions"),
        ],
        [InlineKeyboardButton("🔄 Refresh", callback_data="menu:refresh")],
    ])

    txt = (
        "🌀 *Xchange — Secure Escrow Marketplace*\n"
        "══════════════════════\n"
        f"{card}\n"
        "══════════════════════\n"
        "_Buy • Sell • Escrow • Trade Safely_\n"
        "Trusted peer-to-peer marketplace inside Telegram.\n"
    )

    return kb, txt



# ---------------- SHOP UI ----------------
def build_shop_keyboard():
    items = enumerate_all_products()
    rows, text_lines = [], []

    for it in items:
        text_lines.append(
            f"{it.get('emoji','🛍')} *{it['name']}* — `${it['price']:.2f}`"
        )
        rows.append([
            InlineKeyboardButton(f"💰 Buy ${it['price']:.2f}", callback_data=f"buy:{it['sku']}:1"),
            InlineKeyboardButton("➕ Cart", callback_data=f"cart_add:{it['sku']}"),
            InlineKeyboardButton("💬 Chat Seller", callback_data=f"contact:{it['sku']}:{it.get('seller_id',0)}"),
        ])

    rows.append([InlineKeyboardButton("🔍 Search Items", callback_data="shop:search")])
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="menu:main")])

    text = (
        "🛍 **Xchange Marketplace**\n"
        "Browse products or list your own.\n\n"
        + ("\n".join(text_lines) if text_lines else "_No items yet — be the first to sell._")
    )

    return text, InlineKeyboardMarkup(rows)



# ========================================================
# CART UI 
# ========================================================

async def cart_checkout_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Consolidated cart checkout – user selects payment rail (Stripe / PayNow / NETS).
    """
    q = update.callback_query
    uid = update.effective_user.id

    cart = shopping_cart.get_user_cart(uid)
    if not cart:
        return await q.answer("Your cart is empty.", show_alert=True)

    total = sum(item["price"] * item["qty"] for item in cart.values())
    line_count = len(cart)

    txt = (
        "🧾 *Cart Checkout*\n\n"
        f"• Items: *{line_count}*\n"
        f"• Total: *${total:.2f}*\n\n"
        "_Select a payment method to continue:_"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Stripe (Card)", callback_data=f"stripe_cart:{total}")],
        [InlineKeyboardButton("🇸🇬 PayNow QR (Demo)", callback_data=f"paynow_cart:{total}")],
        [InlineKeyboardButton("🟦 NETS QR (Sandbox)", callback_data=f"nets_cart:{total}")],
        [InlineKeyboardButton("🔙 Back to Cart", callback_data="menu:cart")],
    ])

    return await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def stripe_cart_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE, total: float):
    """
    Stripe checkout for entire cart as a single line item.
    """
    total_cents = int(float(total) * 100)

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Cart Checkout"},
                    "unit_amount": total_cents,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )
    except Exception as e:
        return await update.callback_query.edit_message_text(f"Stripe error: `{e}`")

    kb = InlineKeyboardMarkup([
    [InlineKeyboardButton("💳 Pay with Stripe", url=checkout_url)],
    [InlineKeyboardButton("🔙 Cancel", callback_data="menu:shop")],
])

    await update.callback_query.edit_message_text(
        "💳 *Stripe Checkout*\n\n"
        f"*Item:* {item['name']} x{qty}\n"
        f"*Total:* ${total:.2f}\n\n"
        "_Tap the button below to complete payment securely._",
        reply_markup=kb,
        parse_mode=ParseMode.MARKDOWN,
)



async def show_paynow_cart(update: Update, context: ContextTypes.DEFAULT_TYPE, total: float):
    """
    Fake PayNow QR for the entire cart.
    """
    q = update.callback_query
    qr = generate_paynow_qr(float(total), "Cart Checkout")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I HAVE PAID", callback_data="cart:confirm_payment")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cart:cancel")],
    ])

    await q.message.reply_photo(
        photo=InputFile(qr, filename="cart_paynow.png"),
        caption=(
            "🇸🇬 *Demo PayNow – Cart*\n\n"
            f"Amount: *${float(total):.2f}*\n\n"
            "_After test payment, tap **I HAVE PAID** to continue._"
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb,
    )


async def show_nets_cart(update: Update, context: ContextTypes.DEFAULT_TYPE, total: float):
    """
    NETS QR (sandbox) for the entire cart.
    Expects modules.nets_qr.generate_nets_qr(amount) -> (BytesIO qr, ref_str)
    """
    from modules.nets_qr import generate_nets_qr

    q = update.callback_query
    uid = update.effective_user.id

    qr_img, ref = await generate_nets_qr(float(total))

    # Generic "Cart Checkout" order
    storage.add_order(uid, "Cart Checkout", 1, float(total), "NETS (sandbox)", 0)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I PAID (Simulate)", callback_data=f"payconfirm:{ref}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"paycancel:{ref}")],
        [InlineKeyboardButton("🏠 Back to Home", callback_data="menu:main")],
    ])

    await q.message.reply_photo(
        photo=InputFile(qr_img, filename=f"nets_cart_{ref}.png"),
        caption=(
            "🟦 *NETS QR – Cart (Sandbox)*\n\n"
            f"Total: *${float(total):.2f}*\n"
            f"Ref: `{ref}`\n\n"
            "_Scan with the NETS sandbox app and tap **I PAID** to continue._"
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb,
    )


# ---------------- SEARCH PROMPT ----------------
async def ask_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    context.user_data["awaiting_search"] = True
    await q.edit_message_text(
        "🔍 Send the *product name* you want to search for.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def show_search_results(update: Update, context: ContextTypes.DEFAULT_TYPE, results):
    msg = update.effective_message

    if not results:
        await msg.reply_text("No products found for that search 🔎")
        return

    text_lines = []
    rows = []

    for it in results:
        text_lines.append(
            f"{it.get('emoji','🛒')} *{it['name']}* — `${it['price']:.2f}`"
        )
        rows.append([
            InlineKeyboardButton(f"Buy `${it['price']:.2f}`", callback_data=f"buy:{it['sku']}:1"),
            InlineKeyboardButton("🛒 Add to Cart", callback_data=f"cart_add:{it['sku']}"),
            InlineKeyboardButton("💬 Contact Seller", callback_data=f"contact:{it['sku']}:{it.get('seller_id',0)}"),
        ])

    rows.append([InlineKeyboardButton("🏠 Back to Home", callback_data="menu:main")])

    await msg.reply_text(
        "🔍 *Search Results*\n\n" + "\n".join(text_lines),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------- PAYMENTS: SINGLE ITEM ----------------
async def create_stripe_checkout(update, context, sku: str, qty: int):
    import requests

    item = get_any_product_by_sku(sku)
    if not item:
        return await update.callback_query.answer("Item not found.", show_alert=True)

    qty = clamp_qty(qty)
    total = float(item["price"]) * qty
    user_id = update.effective_user.id

    order_id = f"{sku}_{user_id}"

    try:
        # Request Stripe session from FastAPI server
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
        return await update.callback_query.edit_message_text(f"Error: {e}")

    # Save order into escrow
    storage.add_order(
        user_id,
        item["name"],
        qty,
        total,
        "Stripe (Pending)",
        int(item.get("seller_id", 0))
    )

    kb = InlineKeyboardMarkup([
    [InlineKeyboardButton("💳 Pay with Stripe", url=checkout_url)],
    [InlineKeyboardButton("🔙 Cancel", callback_data="menu:shop")],
])

    await update.callback_query.edit_message_text(
        "💳 *Stripe Checkout*\n\n"
        f"*Item:* {item['name']} x{qty}\n"
        f"*Total:* ${total:.2f}\n\n"
        "_Tap the button below to complete payment securely._",
        reply_markup=kb,
        parse_mode=ParseMode.MARKDOWN,
)




async def show_paynow(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, qty: int):
    """
    Fake PayNow flow for a single item.
    """
    q = update.callback_query
    user_id = update.effective_user.id

    item = get_any_product_by_sku(sku)
    if not item:
        return await q.answer("Item not found.", show_alert=True)

    qty = clamp_qty(qty)
    total = float(item["price"]) * qty

    import time, random
    order_ref = f"ORD{int(time.time())}{random.randint(100,999)}"

    storage.add_order(
        user_id,
        item["name"],
        qty,
        total,
        "PayNow (fake)",
        int(item.get("seller_id", 0)),
    )

    qr = generate_paynow_qr(total, item["name"], order_ref)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I HAVE PAID", callback_data=f"payconfirm:{order_ref}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"paycancel:{order_ref}")],
        [InlineKeyboardButton("🏠 Back to Home", callback_data="menu:main")],
    ])

    caption = (
        "🇸🇬 *Demo PayNow – Single Item*\n\n"
        f"*Item:* {item['name']}\n"
        f"*Qty:* {qty}\n"
        f"*Amount:* ${total:.2f}\n\n"
        f"`{qr.url}`\n\n"
        "_Scan the QR (demo) and tap **I HAVE PAID** to move funds into escrow._"
    )

    try:
        await q.message.reply_photo(
            photo=InputFile(qr, filename=f"paynow_{order_ref}.png"),
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb,
        )
    except Exception:
        await q.edit_message_text(
            caption + "\n\n(QR image could not be sent, use the link instead.)",
            reply_markup=kb,
            parse_mode=ParseMode.MARKDOWN,
        )


async def show_nets_qr(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, qty: int):
    """
    NETS QR (sandbox) for a single item.
    Expects modules.nets_qr.generate_nets_qr(amount) -> (BytesIO qr, ref_str)
    """
    from modules.nets_qr import generate_nets_qr

    q = update.callback_query
    user_id = update.effective_user.id

    item = get_any_product_by_sku(sku)
    if not item:
        return await q.answer("Item not found.", show_alert=True)

    qty = clamp_qty(qty)
    total = float(item["price"]) * qty

    qr_img, ref = await generate_nets_qr(total)

    storage.add_order(
        user_id,
        item["name"],
        qty,
        total,
        "NETS (sandbox)",
        int(item.get("seller_id", 0)),
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I PAID (Simulate)", callback_data=f"payconfirm:{ref}")],
        [InlineKeyboardButton("❌ Cancel", callback_data=f"paycancel:{ref}")],
        [InlineKeyboardButton("🏠 Back to Home", callback_data="menu:main")],
    ])

    await q.message.reply_photo(
        photo=InputFile(qr_img, filename=f"nets_{ref}.png"),
        caption=(
            "🟦 *NETS QR – Sandbox*\n\n"
            f"*Item:* {item['name']} x{qty}\n"
            f"*Amount:* ${total:.2f}\n"
            f"*Ref:* `{ref}`\n\n"
            "_Scan with the NETS sandbox app and tap **I PAID** to move funds into escrow._"
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb,
    )


# ---------------- MENU ROUTER ----------------
async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _, tab = q.data.split(":", 1)
    uid = update.effective_user.id

    async def safe_edit(text: str, kb: InlineKeyboardMarkup):
        try:
            return await q.edit_message_text(
                text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            try:
                return await q.edit_message_caption(
                    text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN
                )
            except Exception:
                return await context.bot.send_message(
                    chat_id=uid,
                    text=text,
                    reply_markup=kb,
                    parse_mode=ParseMode.MARKDOWN,
                )

    if tab == "shop":
        txt, kb = build_shop_keyboard()
        return await safe_edit(txt, kb)
    
    if tab == "orders":
        orders = storage.get_user_orders(uid)

        if not orders:
            txt = "📦 *Your Orders*\n\n_No orders yet._"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Back to Home", callback_data="menu:main")]
            ])
            return await safe_edit(txt, kb)

        lines = []
        buttons = []

        for oid, o in orders.items():
            lines.append(
                f"• `{oid}` — *{o['item']}* — `${o['amount']:.2f}`\n"
                f"  Status: `{o['status']}`"
            )

            buttons.append([
                InlineKeyboardButton("🔍 View", callback_data=f"order:view:{oid}")
            ])

        buttons.append([
            InlineKeyboardButton("🏠 Back to Home", callback_data="menu:main")
        ])

        txt = "📦 *Your Orders*\n\n" + "\n\n".join(lines)

        return await safe_edit(txt, InlineKeyboardMarkup(buttons))


    if tab == "cart":
        return await shopping_cart.view_cart(update, context)

    if tab == "wallet":
        bal = storage.get_balance(uid)
        pub = wallet.ensure_user_wallet(uid)["public_key"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Deposit", callback_data="wallet:deposit")],
            [InlineKeyboardButton("📤 Withdraw", callback_data="wallet:withdraw")],
            [InlineKeyboardButton("🏠 Back to Home", callback_data="menu:main")],
        ])
        return await safe_edit(
        "💼 **Wallet — Xchange Account**\n"
        "───────────────\n"
        f"• Fiat Balance: `${bal:.2f}`\n"
        f"• Solana Wallet:\n`{pub}`\n\n"
        "_Use deposit/withdraw to move funds in or out._",
        kb,
    )


    if tab == "messages":
        threads = storage.load_json(storage.MESSAGES_FILE)
        btns = [
            [InlineKeyboardButton(f"💬 {v['product']['name']}", callback_data=f"chat:open:{k}")]
            for k, v in threads.items()
            if uid in (v.get("buyer_id"), v.get("seller_id"))
        ]
        btns.append([InlineKeyboardButton("🏠 Back to Home", callback_data="menu:main")])
        txt = (
            "💌 *Your Conversations*\n\n_Select a thread to re-open._"
            if len(btns) > 1
            else "No chats yet."
        )
        return await safe_edit(txt, InlineKeyboardMarkup(btns))

    if tab == "sell":
        txt, kb = seller.build_seller_menu(storage.get_role(uid))
        return await safe_edit(txt, kb)

    if tab == "functions":
        return await show_functions_menu(update, context)

    if tab in ("main", "refresh"):
        kb, txt = build_main_menu(storage.get_balance(uid))
        return await safe_edit(txt, kb)


# ===================== CART ACTION HANDLERS =====================

async def on_buy(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, qty: int):
    """
    Single item buy screen – choose payment rail.
    """
    q = update.callback_query
    item = get_any_product_by_sku(sku)
    if not item:
        return await q.answer("Item not found.", show_alert=True)

    qty = clamp_qty(qty)
    total = float(item["price"]) * qty

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Stripe (Card)", callback_data=f"stripe:{sku}:{qty}")],
        [InlineKeyboardButton("🇸🇬 PayNow QR (Demo)", callback_data=f"paynow:{sku}:{qty}")],
        [InlineKeyboardButton("🟦 NETS QR (Sandbox)", callback_data=f"nets:{sku}:{qty}")],
        [InlineKeyboardButton("🔙 Back to Shop", callback_data="back_to_shop")],
    ])

    txt = (
        f"{item.get('emoji','🛒')} *{item['name']}*\n"
        f"Qty: *{qty}*\n"
        f"Total: *${total:.2f}*\n\n"
        "_Select a payment method to continue:_"
    )

    await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def on_qty(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, qty: int):
    """
    Quantity adjuster UI before checkout.
    """
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
            InlineKeyboardButton("+", callback_data=f"qty:{sku}:{qty+1}"),
        ],
        [InlineKeyboardButton("✅ Checkout", callback_data=f"checkout:{sku}:{qty}")],
        [InlineKeyboardButton("🔙 Back to Shop", callback_data="back_to_shop")],
    ])

    txt = (
        f"{item.get('emoji','🛒')} *{item['name']}*\n"
        f"Price: `${item['price']:.2f}`\n"
        f"Qty: *{qty}*\n"
        f"Total: *${total:.2f}*\n\n"
        "_Adjust quantity, then confirm checkout._"
    )

    await q.edit_message_text(txt, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def on_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, qty: int):
    """
    On "Checkout" from qty selector → reopen on_buy with that qty.
    """
    await on_buy(update, context, sku, qty)


async def show_post_payment_options(
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    order_id: str,
    seller_id: int,
):
    """
    After payment confirmed + funds in escrow, show post-payment control
    to buyer and notify seller.
    """
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 I Have Shipped", callback_data=f"ship:{order_id}")],
        [InlineKeyboardButton("✅ I Received My Item", callback_data=f"recv:{order_id}")],
        [InlineKeyboardButton("❗ Report Issue", callback_data=f"dispute:{order_id}")],
    ])

    # Notify buyer
    await context.bot.send_message(
        chat_id,
        f"💠 *Order `{order_id}` is now in escrow.*\n\n"
        "Seller will ship your item. Once you receive it, confirm to release funds.",
        reply_markup=kb,
        parse_mode=ParseMode.MARKDOWN,
    )

    # Optional: notify seller (if info is available)
    try:
        order = storage.get_order(order_id)
        seller_id = int(order.get("seller_id", seller_id))
        if seller_id:
            await context.bot.send_message(
                seller_id,
                f"📦 New paid order in escrow: `{order_id}`.\n"
                "Ship the item and keep the buyer updated in chat.",
                parse_mode=ParseMode.MARKDOWN,
            )
    except Exception:
        pass


# ===========================
# ESCROW PAY CONFIRM HANDLERS
# ===========================
async def handle_pay_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str):
    q = update.callback_query

    # 1️⃣ Move order into escrow
    storage.update_order_status(order_id, "escrow_hold")

    # 2️⃣ 🔽 DEDUCT STOCK HERE
    order = storage.get_order(order_id)
    if order:
        sku = order.get("sku")
        qty = int(order.get("qty", 1))

        if sku:
            inventory.deduct_stock(sku, qty)

    msg = (
        "✅ *Payment Confirmed*\n\n"
        f"Order `{order_id}` is now *secured in escrow*.\n"
        "The seller will ship your item next."
    )

    await q.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)



async def handle_pay_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str):
    q = update.callback_query

    order = storage.get_order(order_id)
    if order:
        sku = order.get("sku")
        qty = int(order.get("qty", 1))
        if sku:
            inventory.restore_stock(sku, qty)

    msg = "❌ Payment cancelled. The order has been discarded."
    await q.edit_message_text(msg)


# ===========================
# ESCROW FLOW CONTINUATION
# ===========================
async def handle_mark_shipped(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str):
    """
    Seller marks order as shipped.
    """
    q = update.callback_query
    order = storage.get_order(order_id)

    storage.update_order_status(order_id, "shipped")

    # Notify buyer
    try:
        await context.bot.send_message(
            order["buyer_id"],
            f"📦 *Order `{order_id}` marked as shipped.*\n\n"
            "Once you receive your item, confirm to release payment.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        pass

    msg = f"✅ Order `{order_id}` set to *shipped*."
    try:
        await q.edit_message_text(msg)
    except Exception:
        await q.message.reply_text(msg)


async def handle_release_payment(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str):
    """
    Buyer confirms receipt → release funds to seller.
    """
    q = update.callback_query
    order = storage.get_order(order_id)

    storage.update_order_status(order_id, "released")

    # Notify seller
    try:
        await context.bot.send_message(
            order["seller_id"],
            f"💰 *Payment released* for order `{order_id}`.\n"
            "Thank you for using the marketplace.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        pass

    msg = (
        f"🎉 *Payment Released*\n\n"
        f"Escrow for order `{order_id}` has been closed.\n"
        "Enjoy your item!"
    )
    try:
        await q.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await q.message.reply_text(msg)


async def handle_dispute_case(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str):
    """
    Buyer opens a dispute for an order in escrow.
    """
    q = update.callback_query
    order = storage.get_order(order_id)

    storage.update_order_status(order_id, "disputed")

    # Notify admin
    try:
        if ADMIN_ID:
            await context.bot.send_message(
                ADMIN_ID,
                "🚨 *Dispute Opened*\n\n"
                f"Order: `{order_id}`\n"
                f"Item: {order['item']}\n"
                f"Buyer: `{order['buyer_id']}`\n"
                f"Seller: `{order['seller_id']}`\n",
                parse_mode=ParseMode.MARKDOWN,
            )
    except Exception:
        pass

    msg = (
        f"⚠️ *Dispute opened* for order `{order_id}`.\n\n"
        "An admin will review this case and decide how to resolve the funds in escrow."
    )
    try:
        await q.edit_message_text(msg, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        await q.message.reply_text(msg)


# ===========================================================
# ✅ ADMIN DISPUTE PANEL
# ===========================================================
async def admin_open_disputes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id

    if uid != ADMIN_ID:
        return await q.answer("🚫 Admin only.", show_alert=True)

    disputes = storage.get_all_disputed_orders()

    if not disputes:
        return await q.edit_message_text(
            "✅ No active disputes at the moment.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Back to Home", callback_data="menu:main")]]
            ),
        )

    text = "⚠️ *Active Disputes*\n\n"
    buttons = []

    for oid, o in disputes.items():
        text += (
            f"• `{oid}` — {o['item']} — `${o['amount']:.2f}`\n"
            f"  Buyer: `{o['buyer_id']}` | Seller: `{o['seller_id']}`\n"
            f"  Status: `{o['status']}`\n\n"
        )

        buttons.append([
            InlineKeyboardButton("✅ Refund Buyer", callback_data=f"admin_refund:{oid}"),
            InlineKeyboardButton("💰 Pay Seller", callback_data=f"admin_release:{oid}"),
        ])

    buttons.append([InlineKeyboardButton("🏠 Back to Home", callback_data="menu:main")])

    await q.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def admin_refund(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str):
    q = update.callback_query
    o = storage.get_order(order_id)

    # 🔁 RESTORE STOCK
    sku = o.get("sku")
    qty = int(o.get("qty", 1))
    if sku:
        inventory.restore_stock(sku, qty)

    storage.update_order_status(order_id, "cancelled")
    storage.update_balance(o["buyer_id"], o["amount"])
    await context.bot.send_message(
        o["buyer_id"],
        f"💸 *Refund Processed* for order *{o['item']}*.\n"
        "The funds have been returned to your balance.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def admin_release(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: str):
    q = update.callback_query
    storage.update_order_status(order_id, "released")

    o = storage.get_order(order_id)
    storage.update_balance(o["seller_id"], o["amount"])

    await context.bot.send_message(
        o["buyer_id"],
        f"⚠️ Admin released funds to the seller for *{o['item']}*.",
        parse_mode=ParseMode.MARKDOWN,
    )
    await context.bot.send_message(
        o["seller_id"],
        f"💰 *Payout Released* for order `{order_id}`.",
        parse_mode=ParseMode.MARKDOWN,
    )

    await q.edit_message_text(
        "💰 Seller has been paid.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏠 Back to Home", callback_data="menu:main")]]
        ),
    )


# ===========================================================
# FUNCTIONS MENU (UTILITY PANEL)
# ===========================================================
async def show_functions_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Simple functions / utilities menu – extend with more tools later.
    """
    q = update.callback_query

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 View Disputes (Admin)", callback_data="admin:disputes")],
        [InlineKeyboardButton("🏠 Back to Home", callback_data="menu:main")],
    ])

    txt = (
        "⚙️ *Functions Panel*\n\n"
        "Utilities and admin tools for the marketplace.\n"
        "More controls can be added here later (reports, analytics, etc.)."
    )

    await q.edit_message_text(txt, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
