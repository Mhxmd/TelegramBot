# ==========================================
# Shopping Cart (DICT MODE)
# ==========================================

import json
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode


CART_FILE = "cart.json"
SELLER_PRODUCTS_FILE = "seller_products.json"


# ================================
# PRODUCT LOADING
# ================================

BUILTIN_PRODUCTS = {
    "cat": {"sku": "cat", "name": "Cat Plush", "price": 15, "emoji": "🐱", "seller_id": 0},
    "hoodie": {"sku": "hoodie", "name": "Hoodie", "price": 30, "emoji": "🧥", "seller_id": 0},
    "blackcap": {"sku": "blackcap", "name": "Black Cap", "price": 12, "emoji": "🧢", "seller_id": 0},
}


def load_all_products():
    products = dict(BUILTIN_PRODUCTS)

    if os.path.exists(SELLER_PRODUCTS_FILE):
        try:
            with open(SELLER_PRODUCTS_FILE, "r") as f:
                data = json.load(f)
                for seller_id, items in data.items():
                    for it in items:
                        if "sku" in it:
                            products[it["sku"]] = it
        except:
            pass

    return products


def get_any_product_by_sku(sku):
    return load_all_products().get(sku)


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
    return load_cart().get(str(uid), {})


def save_user_cart(uid, cart):
    data = load_cart()
    data[str(uid)] = cart
    save_cart(data)


def get_total(uid):
    cart = get_user_cart(uid)
    return sum(item["price"] * item["qty"] for item in cart.values())


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
    return True


async def change_quantity(update, context, sku, delta):
    q = update.callback_query
    uid = update.effective_user.id
    cart = get_user_cart(uid)

    # If item exists, adjust qty
    if sku in cart:
        new_qty = cart[sku]["qty"] + delta

        # NEW RULE: if new qty <= 0 → remove item and return to shop
        if new_qty <= 0:
            remove_from_cart(uid, sku)

            # Return to shop page, NOT full cart
            from modules import ui
            txt, kb = ui.build_shop_keyboard(uid)
            return await q.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

        # Normal update
        update_quantity(uid, sku, new_qty)

    # Detect if coming from mini-panel
    message_text = q.message.text or ""
    if "Added to cart!" in message_text:
        return await show_add_to_cart_feedback(update, context, sku)

    return await view_cart(update, context)



async def remove_item(update, context, sku):
    uid = update.effective_user.id
    remove_from_cart(uid, sku)
    return await view_cart(update, context)


# ========================================================
# ADD-TO-CART FEEDBACK UI
# ========================================================

async def show_add_to_cart_feedback(update, context, sku):
    q = update.callback_query
    uid = update.effective_user.id

    cart = get_user_cart(uid)
    item = cart.get(sku)

    # If item was removed (qty = 0)
    if not item:
        from modules import ui
        txt, kb = ui.build_shop_keyboard(uid)
        return await q.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

    qty = item["qty"]

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➖", callback_data=f"cart:subqty:{sku}"),
            InlineKeyboardButton(f"{qty}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"cart:addqty:{sku}")
        ],
        [InlineKeyboardButton("🛒 Go to Cart", callback_data="cart:view")],
        [InlineKeyboardButton("🏠 Back", callback_data="menu:shop")],
    ])

    msg = f"✔ *Added to cart!* ({item['name']})\nQuantity: *{qty}*"

    return await q.edit_message_text(
        msg, parse_mode="Markdown", reply_markup=kb
    )




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

    rows.append([InlineKeyboardButton("🧹 Clear All", callback_data="cart:clear_all")])
    rows.append([InlineKeyboardButton("💳 Checkout All", callback_data="cart:checkout_all")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])

    return await q.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(rows))

#CLEAR ALL
async def clear_all(update, context):
    uid = update.effective_user.id
    clear_cart(uid)

    q = update.callback_query
    return await q.edit_message_text(
        "🧹 *Your cart has been cleared!*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛍 Shop", callback_data="menu:shop")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
        ])
    )

