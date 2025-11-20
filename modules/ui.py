"""
ui.py – FINAL V2 SQL UI Layer
Fully compatible with bot.py (SQL-only) and db.py
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from modules import db



# ================================================================
# MAIN MENU
# ================================================================

async def build_main_menu(user_id: int):
    user = await modules.get_user_by_id(user_id)
    wallet = await modules.get_or_create_wallet(user_id)

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
        [InlineKeyboardButton("🛒 View Cart", callback_data="v2:cart:view")],
        [InlineKeyboardButton("📬 Orders", callback_data="v2:buyer:orders")],
        [InlineKeyboardButton("💼 Wallet", callback_data="v2:wallet:dashboard")],
    ]

    if role == "seller":
        rows.append([InlineKeyboardButton("📦 My Products", callback_data="v2:seller:products")])
        rows.append([InlineKeyboardButton("➕ Add Product", callback_data="v2:seller:add")])

    if role == "admin":
        rows.append([InlineKeyboardButton("🛠 Admin Panel", callback_data="v2:admin:panel")])

    return text, InlineKeyboardMarkup(rows)


# ================================================================
# CATEGORY MENU
# ================================================================

def build_category_menu(categories):
    rows = []
    for cat in categories:
        rows.append([InlineKeyboardButton(cat, callback_data=f"v2:shop:cat:{cat}")])

    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")])

    text = "🛍 *Shop Categories*\n\nChoose a category:"
    return text, InlineKeyboardMarkup(rows)


# ================================================================
# PRODUCT PHOTO CARD
# ================================================================

def build_product_photo_card(product: dict, page: int, total_pages: int):
    pid = product["product_id"]
    title = product["title"]
    desc = product["description"]
    price = float(product["price"])
    stock = product["stock_quantity"]
    category = product["category_name"]
    image_url = product.get("image_url") or product.get("main_image") or (
        product["images"][0] if product.get("images") else None
    )

    caption = (
        f"🧺 *{title}*\n"
        f"💵 Price: *${price:.2f}*\n"
        f"📦 Stock: `{stock}`\n\n"
        f"{desc}\n\n"
        f"Page {page}/{total_pages}"
    )

    buttons = [
        [
            InlineKeyboardButton("⬅️ Prev", callback_data=f"v2:shop:page:{category}:{page - 1}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"v2:shop:page:{category}:{page + 1}")
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
# ORDER LIST
# ================================================================

def build_orders_list(orders, for_role, page, total_pages):
    if not orders:
        return (
            "📦 No orders found.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]])
        )

    lines = []
    for o in orders:
        lines.append(
            f"• *Order #{o['order_id']}*\n"
            f"Status: `{o['order_status']}`\n"
            f"Total: *${float(o['total_amount']):.2f}*\n"
        )

    text = "📬 *Your Orders*\n\n" + "\n".join(lines)
    text += f"\nPage {page}/{total_pages}"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ Prev", callback_data=f"v2:buyer:orders_page:{page - 1}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"v2:buyer:orders_page:{page + 1}")
        ],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]
    ])

    return text, kb


# ================================================================
# ORDER SUMMARY CARD
# ================================================================

def build_order_summary(order, product, buyer, seller, for_role):
    text = (
        f"📦 *Order #{order['order_id']}*\n\n"
        f"🛍 Product: *{product['title']}*\n"
        f"💵 Amount: *${float(order['total_amount']):.2f}*\n"
        f"🔧 Status: `{order['order_status']}`\n\n"
        f"👤 Buyer: @{buyer['username']}\n"
        f"🛒 Seller: @{seller['username']}\n"
    )

    rows = []

    if for_role == "buyer":
        rows.append([
            InlineKeyboardButton("❗ Raise Dispute", callback_data=f"v2:order:dispute:{order['order_id']}")
        ])

    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")])

    return text, InlineKeyboardMarkup(rows)


# ================================================================
# PAYMENT METHOD MENU
# ================================================================

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
        [InlineKeyboardButton("🔙 Menu", callback_data="v2:menu:main")]
    ])

    return text, kb


# ================================================================
# PAYNOW QR (FAKE PLACEHOLDER – REAL PAYNOW REQUIRES API)
# ================================================================

def build_paynow_qr(order_id, amount):
    text = (
        f"📱 *PayNow Payment*\n\n"
        f"Order: `{order_id}`\n"
        f"Amount: *${amount:.2f}*\n\n"
        "_This is a placeholder QR. Real PayNow requires an SGQR issuer._"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I HAVE PAID", callback_data=f"v2:pay:confirm:{order_id}")],
        [InlineKeyboardButton("🔙 Menu", callback_data="v2:menu:main")]
    ])

    return text, kb


# ================================================================
# CART VIEW (SQL ONLY)
# ================================================================

async def build_cart_view(user_id):
    items = await modules.cart_get(user_id)

    if not items:
        return (
            "🛒 *Your cart is empty*",
            InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]])
        )

    lines = []
    for it in items:
        lines.append(
            f"• *{it['title']}* × {it['quantity']} — ${float(it['price'])*it['quantity']:.2f}"
        )

    total = sum(float(i["price"]) * i["quantity"] for i in items)

    text = (
        "🛒 *Your Cart*\n\n" +
        "\n".join(lines) +
        f"\n\nTotal: *${total:.2f}*"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Checkout", callback_data="v2:checkout_cart")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]
    ])

    return text, kb


# ================================================================
# WALLET
# ================================================================

def build_wallet_dashboard(wallet_row, user_row):
    balance = float(wallet_row["balance"])
    sol = wallet_row["solana_address"]

    text = (
        "💼 *Wallet*\n\n"
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
    text = "🛠 *Admin Panel*\nChoose an option:"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 View Stats", callback_data="v2:admin:stats")],
        [InlineKeyboardButton("🛍 Products", callback_data="v2:admin:products")],
        [InlineKeyboardButton("👥 Users", callback_data="v2:admin:users")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]
    ])

    return text, kb
