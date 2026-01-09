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
# BUILT-IN PRODUCTS
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
# CART STORAGE
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

def clear_cart(uid):
    data = load_cart()
    data[str(uid)] = {}
    save_cart(data)

# ======================================
# MAIN CART OPERATIONS
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
# ADD ITEM
# ======================================
async def add_item(update, context, sku):
    uid = update.effective_user.id
    add_to_cart(uid, sku)
    return True

# ======================================
# CHANGE QTY
# ======================================
async def change_quantity(update, context, sku, delta):
    q = update.callback_query
    uid = update.effective_user.id
    cart = get_user_cart(uid)

    if sku in cart:
        new_qty = cart[sku]["qty"] + delta
        if new_qty <= 0:
            remove_from_cart(uid, sku)
            from modules import ui
            txt, kb = ui.build_shop_keyboard(uid)
            return await q.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")
        update_quantity(uid, sku, new_qty)

    return await view_cart(update, context)

# ======================================
# REMOVE ITEM
# ======================================
async def remove_item(update, context, sku):
    uid = update.effective_user.id
    remove_from_cart(uid, sku)
    return await view_cart(update, context)

# ======================================
# SHOW ADD-TO-CART MINI PANEL
# ======================================
async def show_add_to_cart_feedback(update, context, sku):
    q = update.callback_query
    uid = update.effective_user.id
    cart = get_user_cart(uid)

    item = cart.get(sku)
    if not item:
        from modules import ui
        txt, kb = ui.build_shop_keyboard(uid)
        return await q.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

    qty = item["qty"]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➖", callback_data=f"cart:subqty:{sku}"),
         InlineKeyboardButton(str(qty), callback_data="noop"),
         InlineKeyboardButton("➕", callback_data=f"cart:addqty:{sku}")],
        [InlineKeyboardButton("🛒 Go to Cart", callback_data="cart:view")],
        [InlineKeyboardButton("🏠 Back", callback_data="menu:shop")]
    ])

    return await q.edit_message_text(
        f"✔ *Added to cart!* {item['name']}\nQty: *{qty}*",
        parse_mode="Markdown",
        reply_markup=kb
    )

# ======================================
# VIEW CART (CLEAN NEW UI)
# ======================================
# ======================================
# VIEW CART (NATIVE PAYMENTS UPDATE)
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

    text_lines = ["🛒 *Your Cart*\n"]
    rows = []
    total = 0

    for sku, item in cart.items():
        name = item["name"]
        emoji = item.get("emoji", "🛒")
        price = float(item["price"])
        qty = item["qty"]
        subtotal = price * qty
        total += subtotal

        text_lines.append(f"{emoji} *{name}* — `${price:.2f}` × {qty} = *${subtotal:.2f}*")

        rows.append([
            InlineKeyboardButton("➖", callback_data=f"cart:subqty:{sku}"),
            InlineKeyboardButton(str(qty), callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"cart:addqty:{sku}"),
            InlineKeyboardButton("❌ Remove", callback_data=f"cart:remove:{sku}")
        ])

    text_lines.append(f"\n💰 *Total:* `${total:.2f}`")

    # ==========================================
    # TELEGRAM NATIVE PAYMENT OPTIONS
    # ==========================================
    # These callback_data strings must be handled in your bot's main handler 
    # to call context.bot.send_invoice()
    
    rows.append([InlineKeyboardButton("💳 Pay via Smart Glocal", callback_data=f"pay_native:smart_glocal:{total:.2f}")])
    rows.append([InlineKeyboardButton("🇸🇬 Pay via Redsys", callback_data=f"pay_native:redsys:{total:.2f}")])
    
    # Optional: Keep your external checkout menu if needed
    # rows.append([InlineKeyboardButton("🌐 Other Payment Methods", callback_data=f"cart_checkout_menu:{total:.2f}")])

    rows.append([InlineKeyboardButton("🧹 Clear All", callback_data="cart:clear_all")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])

    return await q.edit_message_text(
        "\n".join(text_lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows)
    )

# ======================================
# CLEAR ALL
# ======================================
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