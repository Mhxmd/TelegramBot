# ==========================================
# Shopping Cart (DICT MODE)
# ==========================================

import json
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

# ================================
# FILE PATHS
# ================================
CART_FILE = "cart.json"
SELLER_PRODUCTS_FILE = "seller_products.json"

# ================================
# LOAD PRODUCTS (NO ui.py import)
# ================================
BUILTIN_PRODUCTS = {
    "cat": {"sku": "cat", "name": "Cat Plush", "price": 15, "emoji": "🐱", "seller_id": 0},
    "hoodie": {"sku": "hoodie", "name": "Hoodie", "price": 30, "emoji": "🧥", "seller_id": 0},
    "blackcap": {"sku": "blackcap", "name": "Black Cap", "price": 12, "emoji": "🧢", "seller_id": 0},
}

def load_all_products():
    """Merge built-in items + seller uploaded items."""
    products = dict(BUILTIN_PRODUCTS)

    if os.path.exists(SELLER_PRODUCTS_FILE):
        try:
            with open(SELLER_PRODUCTS_FILE, "r") as f:
                data = json.load(f)
                for seller_id, items in data.items():
                    for item in items:
                        if "sku" in item:
                            products[item["sku"]] = item
        except:
            pass

    return products


def get_any_product_by_sku(sku):
    products = load_all_products()
    return products.get(sku)


# ======================================
# CART STORAGE HELPERS
# ======================================
def load_cart():
    if not os.path.exists(CART_FILE):
        return {}
    try:
        with open(CART_FILE, "r") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except:
        return {}

def save_cart(data):
    with open(CART_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user_cart(uid):
    data = load_cart()
    return data.get(str(uid), {})

def get_total(uid):
    cart = get_user_cart(uid)
    return sum(item["price"] * item["qty"] for item in cart.values())

def get_cart_item_count(uid):
    return len(get_user_cart(uid))

def save_user_cart(uid, cart_dict):
    data = load_cart()
    data[str(uid)] = cart_dict
    save_cart(data)

def clear_cart(uid):
    data = load_cart()
    data[str(uid)] = {}
    save_cart(data)


# ======================================
# CART OPERATIONS
# ======================================
def add_to_cart(uid, sku):
    cart = get_user_cart(uid)
    product = get_any_product_by_sku(sku)

    if not product:
        return False

    if sku not in cart:
        cart[sku] = {
            "sku": sku,
            "name": product["name"],
            "price": float(product["price"]),
            "qty": 1,
            "emoji": product.get("emoji", "🛍️"),
            "seller_id": product.get("seller_id", 0),
        }
    else:
        cart[sku]["qty"] += 1

    save_user_cart(uid, cart)
    return True


def update_quantity(uid, sku, qty):
    cart = get_user_cart(uid)

    if sku in cart:
        if qty <= 0:
            del cart[sku]
        else:
            cart[sku]["qty"] = qty

    save_user_cart(uid, cart)


def remove_from_cart(uid, sku):
    cart = get_user_cart(uid)
    if sku in cart:
        del cart[sku]
    save_user_cart(uid, cart)


# ======================================
# TELEGRAM HANDLERS
# ======================================
async def add_item(update, context, sku):
    uid = update.effective_user.id
    add_to_cart(uid, sku)
    await update.callback_query.answer("🛒 Added to cart!")


async def change_quantity(update, context, sku, delta):
    uid = update.effective_user.id
    cart = get_user_cart(uid)

    if sku in cart:
        new_qty = cart[sku]["qty"] + delta
        update_quantity(uid, sku, max(0, new_qty))

    return await view_cart(update, context)


async def remove_item(update, context, sku):
    uid = update.effective_user.id
    remove_from_cart(uid, sku)
    return await view_cart(update, context)

# ======================
# WRAPPERS FOR bot.py
# ======================
async def checkout_cart(update, context):
    return await ui.cart_checkout_all(update, context)

async def paynow_cart(update, context):
    q = update.callback_query
    uid = update.effective_user.id
    total = get_total(uid)
    return await ui.show_paynow_cart(update, context, total)


# ======================================
# VIEW CART
# ======================================
async def view_cart(update, context):
    q = update.callback_query
    uid = update.effective_user.id
    cart = get_user_cart(uid)

    if not cart:
        return await q.edit_message_text(
            "🛒 *Your cart is empty.*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛍 Shop", callback_data="menu:shop")],
                [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
            ])
        )

    text = "🛒 *Your Cart*\n\n"
    total = 0
    rows = []

    for sku, item in cart.items():
        subtotal = item["price"] * item["qty"]
        total += subtotal

        text += (
            f"{item['emoji']} *{item['name']}* — "
            f"${item['price']:.2f} × {item['qty']} = *${subtotal:.2f}*\n"
        )

        rows.append([
            InlineKeyboardButton("➖", callback_data=f"cart:subqty:{sku}"),
            InlineKeyboardButton(f"{item['qty']}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"cart:addqty:{sku}"),
            InlineKeyboardButton("❌ Remove", callback_data=f"cart:remove:{sku}")
        ])

    text += f"\n💰 *Total:* ${total:.2f}"

    rows.append([InlineKeyboardButton("🧹 Clear", callback_data="cart_clear")])

    # IMPORTANT: use correct callback for ui.py integration
    rows.append([InlineKeyboardButton("💳 Checkout All", callback_data="cart:checkout_all")])

    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])

    return await q.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))


# ======================================
# PAYMENT CONFIRMATION
# ======================================
async def confirm_payment(update, context):
    uid = update.effective_user.id
    total = get_total(uid)
    clear_cart(uid)

    await update.callback_query.edit_message_text(
        f"✅ Payment confirmed!\nPaid: *${total:.2f}*\nCart cleared.",
        parse_mode="Markdown"
    )
