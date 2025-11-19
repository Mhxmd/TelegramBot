"""
ui.py – FULL V2 SQL UI Layer
Matches db.py + bot.py v2 hybrid marketplace
NO JSON ANYWHERE
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from modules import db

# ================================================================
# MAIN MENU (SQL-ONLY V2)
# ================================================================

import math
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from modules import db   # make sure this import exists at top

async def build_main_menu(user_id: int):
    """
    Loads role + wallet + verification from SQL and builds the home menu.
    """
    user = await db.get_user_by_id(user_id)
    wallet = await db.get_or_create_wallet(user_id)

    role = user["role"]
    balance = float(wallet["balance"])
    verified = user["verification_status"]

    text = (
        "👋 *Marketplace Dashboard*\n\n"
        f"💰 Balance: *${balance:.2f}*\n"
        f"🧩 Role: `{role}`\n"
        f"🔒 Verified: {'Yes' if verified else 'No'}\n"
    )

    rows = [
        [InlineKeyboardButton("🛍 Shop", callback_data="v2:shop:categories")],
        [InlineKeyboardButton("🛒 Cart", callback_data="v2:cart:view")],
        [InlineKeyboardButton("📬 Orders", callback_data="v2:buyer:orders")],
        [InlineKeyboardButton("💼 Wallet", callback_data="v2:wallet:dashboard")],
        [InlineKeyboardButton("💰 Checkout Now", callback_data=f"v2:checkout:{pid}")]

    ]

    if role == "seller":
        rows.append([InlineKeyboardButton("📦 My Products", callback_data="v2:seller:products")])
        rows.append([InlineKeyboardButton("➕ Add Product", callback_data="v2:seller:add")])

    if role == "admin":
        rows.append([InlineKeyboardButton("🛠 Admin Panel", callback_data="v2:admin:panel")])

    kb = InlineKeyboardMarkup(rows)
    return text, kb



# ================================================================
# CATEGORY MENU
# ================================================================

def build_category_menu(categories):
    """
    categories = ["Shoes", "Electronics", "Fashion"]
    """
    rows = []
    for cat in categories:
        rows.append([InlineKeyboardButton(cat, callback_data=f"v2:shop:cat:{cat}")])

    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")])

    text = "🛍 *Shop Categories*\n\nChoose a category:"
    return text, InlineKeyboardMarkup(rows)


# ================================================================
# PRODUCT CARD (PHOTO + CAPTION)
# ================================================================

def build_product_photo_card(product: dict, page: int, total_pages: int):
    """
    product: SQL dict containing:
        product_id, title, description, price, category, stock_quantity, image_url
    """
    pid = product["product_id"]
    title = product["title"]
    desc = product["description"]
    price = float(product["price"])
    stock = product["stock_quantity"]
    cat = product["category"]
    image_url = product.get("image_url") or product.get("main_image")

    caption = (
        f"🧺 *{title}*\n"
        f"💵 Price: *${price:.2f}*\n"
        f"📦 Stock: `{stock}`\n\n"
        f"{desc}\n\n"
        f"Page {page}/{total_pages}"
    )

    buttons = [
        [
            InlineKeyboardButton("⬅️ Prev", callback_data=f"v2:shop:page:{cat}:{page - 1}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"v2:shop:page:{cat}:{page + 1}")
        ],
        [InlineKeyboardButton("🛒 Add to Cart", callback_data=f"v2:cart:add:{pid}:1")],
        [InlineKeyboardButton("🔙 Categories", callback_data="v2:shop:categories")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return {
        "photo_url": image_url,
        "caption": caption,
        "reply_markup": InlineKeyboardMarkup(buttons)
    }


# ================================================================
# ORDERS LIST
# ================================================================

def build_orders_list(orders, for_role: str, page: int, total_pages: int):
    """
    orders = SQL rows from db.get_orders_by_buyer_paginated()
    """
    if not orders:
        return "📦 No orders found.", InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]
        ])

    lines = []
    for o in orders:
        lines.append(
            f"• *Order #{o['order_id']}*\n"
            f"Status: `{o['order_status']}`\n"
            f"Amount: *${float(o['amount']):.2f}*\n"
        )

    text = "📦 *Your Orders*\n\n" + "\n".join(lines)
    text += f"\nPage {page}/{total_pages}"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ Prev", callback_data=f"v2:buyer:orders_page:{page - 1}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"v2:buyer:orders_page:{page + 1}"),
        ],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]
    ])

    return text, kb


# ================================================================
# ORDER SUMMARY CARD
# ================================================================

def build_order_summary(order, product, buyer, seller, for_role: str):
    price = float(order["amount"])

    caption = (
        f"📦 *Order #{order['order_id']}*\n\n"
        f"🛍 Product: *{product['title']}*\n"
        f"💵 Amount: *${price:.2f}*\n"
        f"🔧 Status: `{order['order_status']}`\n\n"
        f"👤 Buyer: @{buyer['username']}\n"
        f"🛒 Seller: @{seller['username']}\n"
    )

    rows = []

    if for_role == "buyer":
        rows.append([
            InlineKeyboardButton("❗ Raise Dispute",
                                 callback_data=f"v2:order:dispute:{order['order_id']}")
        ])

    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")])

    return caption, InlineKeyboardMarkup(rows)

#Payment Method

def build_payment_method_menu(order_id, amount):
    text = (
        f"💰 *Checkout*\n\n"
        f"Order ID: `{order_id}`\n"
        f"Amount: *${amount:.2f}*\n\n"
        "Choose payment method:"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 PayNow", callback_data=f"v2:pay:paynow:{order_id}")],
        [InlineKeyboardButton("💳 Stripe", callback_data=f"v2:pay:stripe:{order_id}")],
        [InlineKeyboardButton("⚡ Solana", callback_data=f"v2:pay:solana:{order_id}")],
        [InlineKeyboardButton("🔙 Back", callback_data="v2:menu:main")]
    ])

    return text, kb


# ================================================================
# WALLET DASHBOARD
# ================================================================

def build_wallet_dashboard(wallet_row, user_row):
    balance = float(wallet_row["balance"])
    sol = wallet_row.get("solana_address", "")

    text = (
        "💼 *Wallet Dashboard*\n\n"
        f"Balance: *${balance:.2f}*\n"
        f"Solana Address:\n`{sol}`\n\n"
        f"Role: `{user_row['role']}`"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="v2:wallet:refresh")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]
    ])

    return text, kb


# ================================================================
# ADMIN PANEL
# ================================================================

def build_admin_panel_menu():
    text = (
        "🔧 *Admin Panel*\n\n"
        "Choose an option:"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 View Stats", callback_data="v2:admin:stats")],
        [InlineKeyboardButton("🛍 Products", callback_data="v2:admin:products")],
        [InlineKeyboardButton("👥 Users", callback_data="v2:admin:users")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]
    ])

    return text, kb
