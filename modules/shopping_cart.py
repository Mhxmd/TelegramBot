# ==========================================
# SHOPPING CART (FULLY STABLE VERSION)
# ==========================================

import json
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from modules import storage

CART_FILE = storage.CART_FILE
SELLER_PRODUCTS_FILE = storage.SELLER_PRODUCTS_FILE


# ------------------------------------------
# BUILT-IN PRODUCTS
# ------------------------------------------
BUILTIN_PRODUCTS = {
    "cat": {"sku": "cat", "name": "Cat Plush", "price": 15, "emoji": "🐱", "seller_id": 0},
    "hoodie": {"sku": "hoodie", "name": "Hoodie", "price": 30, "emoji": "🧥", "seller_id": 0},
    "blackcap": {"sku": "blackcap", "name": "Black Cap", "price": 12, "emoji": "🧢", "seller_id": 0},
}

def load_all_products():
    products = dict(BUILTIN_PRODUCTS)
    if os.path.exists(SELLER_PRODUCTS_FILE):
        try:
            with open(SELLER_PRODUCTS_FILE, "r", encoding="utf-8") as f:
                seller_data = json.load(f)
                for seller_id, items in seller_data.items():
                    for it in items:
                        if "sku" in it:
                            products[it["sku"]] = it
        except:
            pass
    return products

def get_any_product_by_sku(sku):
    return load_all_products().get(sku)


# ------------------------------------------
# CART STORAGE
# ------------------------------------------
def load_cart():
    if not os.path.exists(CART_FILE):
        return {}
    try:
        with open(CART_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except:
        return {}

def save_cart(data):
    os.makedirs(os.path.dirname(CART_FILE), exist_ok=True)
    with open(CART_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_user_cart(uid):
    return load_cart().get(str(uid), {})

def save_user_cart(uid, cart):
    db = load_cart()
    db[str(uid)] = cart
    save_cart(db)

def clear_cart(uid):
    db = load_cart()
    db[str(uid)] = {}
    save_cart(db)


# ------------------------------------------
# CORE CART ACTIONS
# ------------------------------------------
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
            "seller_id": product.get("seller_id", 0)
        }
    else:
        cart[sku]["qty"] += 1

    save_user_cart(uid, cart)
    return True


def update_quantity(uid, sku, q):
    cart = get_user_cart(uid)
    if sku in cart:
        if q <= 0:
            del cart[sku]
        else:
            cart[sku]["qty"] = q
    save_user_cart(uid, cart)


def remove_from_cart(uid, sku):
    cart = get_user_cart(uid)
    if sku in cart:
        del cart[sku]
    save_user_cart(uid, cart)


# ------------------------------------------
# ADD ITEM HANDLER
# ------------------------------------------
async def add_item(update, context, sku):
    uid = update.effective_user.id
    add_to_cart(uid, sku)
    return True


# ------------------------------------------
# MINI PANEL 
# ------------------------------------------
def _is_mini_panel(text):
    return text and "Added to cart!" in text


async def show_add_to_cart_feedback(update, context, sku, source="shop"):

    q = update.callback_query
    uid = update.effective_user.id
    
    context.user_data["mini_source"] = source


    cart = get_user_cart(uid)
    item = cart.get(sku)

    if not item:
        from modules import ui
        txt, kb = ui.build_shop_keyboard(uid)
        return await q.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

    qty = item["qty"]
    price = float(item["price"])
    subtotal = price * qty

    # UI Buttons
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➖", callback_data=f"cart:subqty:{sku}"),
            InlineKeyboardButton(str(qty), callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"cart:addqty:{sku}"),
        ],
        [InlineKeyboardButton("🛒 Go to Cart", callback_data="cart:view")],
        [InlineKeyboardButton(
            "🔙 Back",
                callback_data=(
                     "cart:view" if source == "cart"
                         else "menu:shop" if source == "shop"
                            else f"view_item:{sku}"))]


    ])

    # Mini Panel Text
    text = (
        f"✔ *Added to cart!* {item['name']}\n"
        f"Qty: *{qty}*\n"
        f"💵 Price: `${price:.2f}` × {qty} = *${subtotal:.2f}*"
    )

    return await q.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=kb
    )



# ------------------------------------------
# CHANGE QUANTITY
# ------------------------------------------
async def change_quantity(update, context, sku, delta):
    q = update.callback_query
    uid = update.effective_user.id
    cart = get_user_cart(uid)

    if sku not in cart:
        return await view_cart(update, context)

    new_qty = cart[sku]["qty"] + delta

    # ------------------------------------------------------
    # CASE 1: QUANTITY DROPPED TO ZERO → ITEM REMOVED
    # ------------------------------------------------------
    if new_qty <= 0:
        remove_from_cart(uid, sku)

        source = context.user_data.get("mini_source", "shop")

        # Mini panel sources
        if _is_mini_panel(q.message.text or ""):

            if source == "cart":
                return await view_cart(update, context)

            if source == "view":
                from modules import ui
                return await ui.view_item_details(update, context, sku)

            # default = shop
            from modules import ui
            txt, kb = ui.build_shop_keyboard(uid)
            return await q.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

        # Not mini panel → normal cart return
        return await view_cart(update, context)


    # ------------------------------------------------------
    # CASE 2: NORMAL QUANTITY UPDATE
    # ------------------------------------------------------
    update_quantity(uid, sku, new_qty)

    # Inside mini panel → refresh mini panel (NOT view cart)
    if _is_mini_panel(q.message.text or ""):
        source = context.user_data.get("mini_source", "shop")
        return await show_add_to_cart_feedback(update, context, sku, source=source)

    # Not mini panel → update cart normally
    return await view_cart(update, context)



# ------------------------------------------
# VIEW CART (BIG BUTTON UI — CLEAN VERSION)
# ------------------------------------------
async def view_cart(update, context):
    q = update.callback_query
    uid = update.effective_user.id
    cart = get_user_cart(uid)

    # If empty
    if not cart:
        return await q.edit_message_text(
            "🛒 *Your cart is empty.*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🛍 Shop", callback_data="menu:shop")],
                [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
            ])
        )

    rows = []
    total = 0

    # ------------------------------
    # TITLE + TOTAL
    # ------------------------------
    header_text = "🛒 *Your Cart*\n"
    
    # ------------------------------
    # BUILD PRODUCT BUTTONS
    # ------------------------------
    for sku, item in cart.items():
        emoji = item.get("emoji", "🛒")
        name = item["name"]
        price = float(item["price"])
        qty = item["qty"]
        subtotal = price * qty
        total += subtotal
        
        # Build pretty text for the big product button
        btn_text = f"{emoji} {name} — {qty} × ${price:.2f} = ${subtotal:.2f}"

        # Store where mini-panel should return
        context.user_data["mini_source"] = "cart"

        # VERY SMALL remove button
        small_x = "✖️\u200b"

        # Big button (go to mini panel) + tiny ❌
        rows.append([
            InlineKeyboardButton(btn_text, callback_data=f"cart:edit:{sku}:cart"),
            InlineKeyboardButton(small_x, callback_data=f"cart:remove:{sku}")
                ])


    # ------------------------------
    # TOTAL LINE
    # ------------------------------
    header_text += f"💰 *Total:* `${total:.2f}`"

    # ------------------------------
    # PAYMENT OPTIONS
    # ------------------------------
    rows.append([InlineKeyboardButton("💳 Pay via Stripe (Cart)", callback_data=f"stripe_cart:{total:.2f}")])
    rows.append([InlineKeyboardButton("🇸🇬 PayNow (Cart)", callback_data=f"paynow_cart:{total:.2f}")])
    rows.append([InlineKeyboardButton("🇸🇬 PayNow (HitPay)", callback_data=f"hitpay_cart:{total:.2f}")])
    rows.append([InlineKeyboardButton("🚀 Pay with Solana (SOL)", callback_data=f"pay_crypto:solana:{total:.2f}:Cart")])

    # ------------------------------
    # CLEAR + MENU
    # ------------------------------
    rows.append([InlineKeyboardButton("🧹 Clear All", callback_data="cart:clear_all")])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])

    return await q.edit_message_text(
        header_text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(rows)
    )




# This is related to solana payment

def get_cart(user_id):
    """Cart dict for solana/cart flows: {sku: {..item..}}"""
    return get_user_cart(user_id)

# ------------------------------------------
# CLEAR ALL
# ------------------------------------------
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
