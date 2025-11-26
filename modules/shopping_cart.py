# modules/shopping_cart.py
# ==========================================
# 🛒 Telegram Marketplace Shopping Cart Module
# ==========================================
# Handles:
#   - Adding items to cart
#   - Viewing / editing cart
#   - Checking out multiple items
#
# Depends on: modules.storage, modules.ui
# ==========================================

import json
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from modules import storage, ui

CART_FILE = "cart.json"

# ==========================
# Helpers
# ==========================
def load_cart():
    if not os.path.exists(CART_FILE):
        return {}
    with open(CART_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_cart(data):
    with open(CART_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user_cart(user_id: int):
    data = load_cart()
    return data.get(str(user_id), [])

def save_user_cart(user_id: int, items):
    data = load_cart()
    data[str(user_id)] = items
    save_cart(data)

def clear_cart(user_id: int):
    data = load_cart()
    data[str(user_id)] = []
    save_cart(data)

# ==========================
# Add / Remove / Update
# ==========================
def add_to_cart(user_id: int, item):
    cart = get_user_cart(user_id)
    # if item already exists, increase qty
    for it in cart:
        if it["sku"] == item["sku"]:
            it["qty"] += item.get("qty", 1)
            break
    else:
        cart.append(item)
    save_user_cart(user_id, cart)

def remove_from_cart(user_id: int, sku: str):
    cart = get_user_cart(user_id)
    cart = [it for it in cart if it["sku"] != sku]
    save_user_cart(user_id, cart)

def update_quantity(user_id: int, sku: str, new_qty: int):
    cart = get_user_cart(user_id)
    for it in cart:
        if it["sku"] == sku:
            it["qty"] = max(1, new_qty)
    save_user_cart(user_id, cart)

# ==========================
# Telegram UI
# ==========================
async def view_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    cart = get_user_cart(uid)

    if not cart:
        await q.edit_message_text(
            "🛒 *Your cart is empty.*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]]),
        )
        return

    total = sum(it["price"] * it["qty"] for it in cart)
    text = "🛒 *Your Shopping Cart:*\n\n"
    for it in cart:
        text += f"{it.get('emoji','🛍️')} *{it['name']}* — ${it['price']:.2f} × {it['qty']} = *${it['price']*it['qty']:.2f}*\n"

    text += f"\n💰 *Total:* ${total:.2f}"

    # Build buttons
    buttons = []
    for it in cart:
        sku = it["sku"]
        buttons.append([
            InlineKeyboardButton("➕", callback_data=f"cart:addqty:{sku}"),
            InlineKeyboardButton("➖", callback_data=f"cart:subqty:{sku}"),
            InlineKeyboardButton("❌ Remove", callback_data=f"cart:remove:{sku}")
        ])
    buttons.append([InlineKeyboardButton("💳 Checkout All", callback_data="cart:checkout")])
    buttons.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])

    await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(buttons))

async def add_item(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str):
    from modules.ui import get_any_product_by_sku
    q = update.callback_query
    uid = update.effective_user.id
    product = get_any_product_by_sku(sku)

    if not product:
        await q.answer("Item not found!", show_alert=True)
        return

    item = {
        "sku": sku,
        "name": product["name"],
        "price": float(product["price"]),
        "qty": 1,
        "seller_id": product.get("seller_id", 0),
        "emoji": product.get("emoji", "🛍️"),
    }

    add_to_cart(uid, item)
    await q.answer(f"✅ {product['name']} added to cart!", show_alert=False)


async def change_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, delta: int):
    uid = update.effective_user.id
    cart = get_user_cart(uid)
    for it in cart:
        if it["sku"] == sku:
            it["qty"] = max(1, it["qty"] + delta)
    save_user_cart(uid, cart)
    await view_cart(update, context)

async def remove_item(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str):
    uid = update.effective_user.id
    remove_from_cart(uid, sku)
    await view_cart(update, context)

# ==========================
# Checkout
# ==========================
async def checkout_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from modules.ui import show_paynow
    q = update.callback_query
    uid = update.effective_user.id
    cart = get_user_cart(uid)

    if not cart:
        await q.answer("Your cart is empty!", show_alert=True)
        return

    total = sum(it["price"] * it["qty"] for it in cart)
    summary = "\n".join([f"{it['name']} × {it['qty']} = ${it['price']*it['qty']:.2f}" for it in cart])

    caption = (
        f"🧾 *Checkout Summary:*\n\n{summary}\n\n💰 *Total:* ${total:.2f}\n\n"
        "Choose payment method:"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇸🇬 PayNow", callback_data="cart:paynow")],
        [InlineKeyboardButton("💳 Stripe", callback_data="cart:stripe")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
    ])

    await q.edit_message_text(caption, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

async def paynow_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from modules.ui import generate_paynow_qr
    uid = update.effective_user.id
    cart = get_user_cart(uid)
    total = sum(it["price"] * it["qty"] for it in cart)

    qr = generate_paynow_qr(total, "Cart Checkout")
    caption = f"🇸🇬 *PayNow — Cart Checkout*\n\n💰 Total: ${total:.2f}\n\nAfter payment, click *I HAVE PAID*."

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I HAVE PAID", callback_data="cart:confirm_payment")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cart:cancel")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")],
    ])

    await update.callback_query.message.reply_photo(
        photo=qr,
        caption=caption,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cart = get_user_cart(uid)
    total = sum(it["price"] * it["qty"] for it in cart)
    clear_cart(uid)
    await update.callback_query.edit_message_text(
        f"✅ Payment confirmed for *${total:.2f}*!\n\nYour cart has been cleared.",
        parse_mode=ParseMode.MARKDOWN
    )
