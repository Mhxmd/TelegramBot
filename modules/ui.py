# ============================================================
# modules/ui.py — UI LAYER for Marketplace V2
# Dynamic Buyer/Seller/Admin Interface
# ============================================================

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from modules import db


# ============================================================
# MAIN MENU
# ============================================================

async def build_main_menu(user_id: int):
    user = await db.get_user_by_id(user_id)
    wallet = await db.get_or_create_wallet(user_id)

    balance = float(wallet["balance"])
    role = user["role"]

    # Determine if user is a seller (based on products they listed)
    seller_products = await db.get_seller_products(user_id)
    is_seller = len(seller_products) > 0

    # Only show role if admin
    role_line = f"🧩 Role: `{role}`\n" if role == "admin" else ""

    text = (
        "👋 *Marketplace Dashboard*\n\n"
        f"💰 Balance: *${balance:.2f}*\n"
        f"{role_line}"
        f"🔒 Verified: {'Yes' if user['verification_status'] else 'No'}\n"
    )

    # Base menu
    kb = [
        [InlineKeyboardButton("🛍 Shop", callback_data="v2:shop:categories")],
        [InlineKeyboardButton("🛒 View Cart", callback_data="v2:cart:view")],
        [InlineKeyboardButton("📬 Orders", callback_data="v2:buyer:orders")],
        [InlineKeyboardButton("💼 Wallet", callback_data="v2:wallet:dashboard")],
    ]

    # Seller section
    if is_seller:
        kb.append([InlineKeyboardButton("📦 My Products", callback_data="v2:seller:products")])
        kb.append([InlineKeyboardButton("➕ Add Product", callback_data="v2:seller:add")])
    else:
        kb.append([InlineKeyboardButton("📦 Become a Seller", callback_data="v2:seller:become")])

    # Admin UI
    if role == "admin":
        kb.append([InlineKeyboardButton("🛠 Admin Panel", callback_data="v2:admin:panel")])

    return text, InlineKeyboardMarkup(kb)


# ============================================================
# CATEGORY MENU
# ============================================================

def build_category_menu(categories: list):
    rows = [
        [InlineKeyboardButton(cat["category_name"], callback_data=f"v2:shop:cat:{cat['category_name']}")]
        for cat in categories
    ]

    rows.append([InlineKeyboardButton("🏠 Back to Menu", callback_data="v2:menu:main")])

    return (
        "🛍 *Shop Categories*\n\nChoose a category:",
        InlineKeyboardMarkup(rows)
    )


# ============================================================
# PRODUCT PHOTO CARD
# ============================================================

def build_product_photo_card(product, page, total_pages):
    pid = product["product_id"]
    title = product["title"]
    price = float(product["price"])
    desc = product.get("description", "")
    stock = product["stock_quantity"]
    category = product.get("category_name", "Unknown")

    img = product["images"][0] if product.get("images") else None

    caption = (
        f"🧺 *{title}*\n"
        f"💵 Price: *${price:.2f}*\n"
        f"📦 Stock: `{stock}`\n\n"
        f"{desc}\n\n"
        f"Page {page}/{total_pages}"
    )

    kb = [
        [
            InlineKeyboardButton("⬅️ Prev", callback_data=f"v2:shop:page:{category}:{page - 1}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"v2:shop:page:{category}:{page + 1}")
        ],
        [InlineKeyboardButton("🛒 Add to Cart", callback_data=f"v2:cart:add:{pid}:1")],
        [InlineKeyboardButton("↩️ Back to Categories", callback_data="v2:shop:categories")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return {
        "photo_url": img,
        "caption": caption,
        "reply_markup": InlineKeyboardMarkup(kb)
    }

# ============================================================
# CART VIEW
# ============================================================

async def build_cart_view(user_id):
    items = await db.cart_get(user_id)
    if not items:
        return (
            "🛒 *Your cart is empty.*",
            InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]])
        )

    txt = "🛒 *Your Cart*\n\n"
    total = 0

    for it in items:
        subtotal = float(it["price"]) * it["quantity"]
        total += subtotal
        txt += f"• *{it['title']}* × `{it['quantity']}` — *${subtotal:.2f}*\n"

    txt += f"\nTotal: *${total:.2f}*"

    kb = [
        [InlineKeyboardButton("💰 Checkout", callback_data="v2:checkout_cart")],
        [InlineKeyboardButton("🗑 Clear Cart", callback_data="v2:cart:clear")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return txt, InlineKeyboardMarkup(kb)


# ============================================================
# ORDER LIST
# ============================================================

def build_orders_list(orders, for_role, page, total_pages):
    if not orders:
        return (
            "📦 No orders found.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]])
        )

    txt = "📬 *Your Orders*\n\n"
    for o in orders:
        txt += (
            f"*Order #{o['order_id']}*\n"
            f"Status: `{o['order_status']}`\n"
            f"Total: *${float(o['total_amount']):.2f}*\n\n"
        )

    txt += f"Page {page}/{total_pages}"

    kb = [
        [
            InlineKeyboardButton("⬅️ Prev", callback_data=f"v2:buyer:orders_page:{page - 1}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"v2:buyer:orders_page:{page + 1}")
        ],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return txt, InlineKeyboardMarkup(kb)


# ============================================================
# ORDER SUMMARY
# ============================================================

def build_order_summary(order, product, buyer, seller, for_role):
    txt = (
        f"📦 *Order #{order['order_id']}*\n\n"
        f"🛍 Product: *{product['title']}*\n"
        f"💵 Amount: *${float(order['total_amount']):.2f}*\n"
        f"📌 Status: `{order['order_status']}`\n\n"
        f"👤 Buyer: @{buyer['username']}\n"
        f"🏪 Seller: @{seller['username']}\n"
    )

    rows = []

    if for_role == "buyer":
        rows.append([InlineKeyboardButton("❗ Raise Dispute", callback_data=f"v2:order:dispute:{order['order_id']}")])

    if for_role == "seller":
        rows.append([InlineKeyboardButton("📦 Mark Shipped", callback_data=f"v2:seller:ship:{order['order_id']}")])

    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")])

    return txt, InlineKeyboardMarkup(rows)


# ============================================================
# PAYMENT
# ============================================================

def build_payment_method_menu(order_id, amount):
    txt = (
        f"💰 *Checkout*\n\n"
        f"Order ID: `{order_id}`\n"
        f"Amount: *${amount:.2f}*\n\n"
        "Choose a payment method:"
    )

    kb = [
        [InlineKeyboardButton("📱 PayNow", callback_data=f"v2:pay:paynow:{order_id}")],
        [InlineKeyboardButton("💳 Stripe", callback_data=f"v2:pay:stripe:{order_id}")],
        [InlineKeyboardButton("⚡ Solana", callback_data=f"v2:pay:solana:{order_id}")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return txt, InlineKeyboardMarkup(kb)


def build_paynow_qr(order_id, amount):
    txt = (
        f"📱 *PayNow*\n\n"
        f"Order ID: `{order_id}`\n"
        f"Amount: *${amount:.2f}*\n\n"
        "_This is a placeholder SGQR._"
    )

    kb = [
        [InlineKeyboardButton("✅ I HAVE PAID", callback_data=f"v2:pay:confirm:{order_id}")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return txt, InlineKeyboardMarkup(kb)


# ============================================================
# WALLET
# ============================================================

def build_wallet_dashboard(wallet, user):
    balance = float(wallet["balance"])
    sol = wallet["solana_address"]

    txt = (
        "💼 *Wallet*\n\n"
        f"💰 Balance: *${balance:.2f}*\n"
        f"⚡ Solana Address:\n`{sol}`\n"
        f"🧩 Role: `{user['role']}`"
    )

    kb = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="v2:wallet:refresh")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return txt, InlineKeyboardMarkup(kb)


# ============================================================
# SELLER PANEL
# ============================================================

def build_seller_dashboard():
    txt = (
        "📦 *Seller Dashboard*\n\n"
        "Manage your products:"
    )
    kb = [
        [InlineKeyboardButton("📦 My Products", callback_data="v2:seller:products")],
        [InlineKeyboardButton("➕ Add Product", callback_data="v2:seller:add")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]
    return txt, InlineKeyboardMarkup(kb)


def build_seller_product_list(products):
    if not products:
        return (
            "📦 *You haven't listed any products yet.*",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Product", callback_data="v2:seller:add")],
                [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
            ])
        )

    txt = "📦 *Your Products*\n\n"
    kb = []

    for p in products:
        txt += f"• *{p['title']}* — ${float(p['price']):.2f}\n"
        kb.append([InlineKeyboardButton(f"View {p['title']}", callback_data=f"v2:seller:view:{p['product_id']}")])

    kb.append([InlineKeyboardButton("➕ Add Product", callback_data="v2:seller:add")])
    kb.append([InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")])

    return txt, InlineKeyboardMarkup(kb)


def build_seller_product_card(product):
    img = product["images"][0] if product["images"] else None

    caption = (
        f"📦 *{product['title']}*\n"
        f"💵 Price: *${float(product['price']):.2f}*\n"
        f"📦 Stock: `{product['stock_quantity']}`\n\n"
        f"{product['description']}"
    )

    kb = [
        [InlineKeyboardButton("✏ Edit Title", callback_data=f"v2:seller:edit_title:{product['product_id']}")],
        [InlineKeyboardButton("📝 Edit Description", callback_data=f"v2:seller:edit_desc:{product['product_id']}")],
        [InlineKeyboardButton("💰 Edit Price", callback_data=f"v2:seller:edit_price:{product['product_id']}")],
        [InlineKeyboardButton("📦 Edit Stock", callback_data=f"v2:seller:edit_stock:{product['product_id']}")],
        [InlineKeyboardButton("🗑 Delete Product", callback_data=f"v2:seller:delete:{product['product_id']}")],
        [InlineKeyboardButton("↩ Back", callback_data="v2:seller:products")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return {
        "photo_url": img,
        "text": caption,
        "reply_markup": InlineKeyboardMarkup(kb)
    }


def build_seller_after_delete_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 My Products", callback_data="v2:seller:products")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ])

# ============================================================
# ADMIN PANEL UI
# ============================================================

def build_admin_panel_menu():
    txt = "🛠 *Admin Panel*\nChoose an option:"
    kb = [
        [InlineKeyboardButton("📊 Stats", callback_data="v2:admin:stats")],
        [InlineKeyboardButton("👥 Users", callback_data="v2:admin:users")],
        [InlineKeyboardButton("🛍 Products", callback_data="v2:admin:products")],
        [InlineKeyboardButton("⚖ Disputes", callback_data="v2:admin:disputes")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]
    return txt, InlineKeyboardMarkup(kb)


# ============================================================
# ADMIN — STATS
# ============================================================

def build_admin_stats(stats):
    txt = (
        "📊 *System Statistics*\n\n"
        f"👥 Users: *{stats['user_count']}*\n"
        f"🛍 Products: *{stats['product_count']}*\n"
        f"📦 Orders: *{stats['order_count']}*\n"
        f"💸 Payments: *{stats['payment_count']}*\n"
        f"⚖ Disputes: *{stats['dispute_count']}*\n"
    )
    kb = [
        [InlineKeyboardButton("↩ Back", callback_data="v2:admin:panel")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]
    ]
    return txt, InlineKeyboardMarkup(kb)


# ============================================================
# ADMIN — USER LIST
# ============================================================

async def build_admin_user_list(users, page, total_pages):
    txt = "👥 *All Users*\n\n"
    for u in users:
        txt += (
            f"• @{u['username']} — `{u['role']}`\n"
            f"ID: `{u['user_id']}`\n\n"
        )

    txt += f"Page {page}/{total_pages}"

    kb = [
        [
            InlineKeyboardButton("⬅ Prev", callback_data=f"v2:admin:users_page:{page-1}"),
            InlineKeyboardButton("➡ Next", callback_data=f"v2:admin:users_page:{page+1}")
        ],
        [InlineKeyboardButton("↩ Back", callback_data="v2:admin:panel")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]
    ]

    return txt, InlineKeyboardMarkup(kb)


# ============================================================
# ADMIN — USER VIEW
# ============================================================

def build_admin_user_view(user, wallet):
    txt = (
        f"👤 *User Info*\n\n"
        f"ID: `{user['user_id']}`\n"
        f"Username: @{user['username']}\n"
        f"Role: `{user['role']}`\n"
        f"Verified: `{user['verification_status']}`\n\n"
        f"💼 *Wallet*\n"
        f"Balance: *${float(wallet['balance']):.2f}*\n"
        f"Status: `{wallet['status']}`\n"
        f"Solana: `{wallet['solana_address']}`"
    )

    kb = [
        [
            InlineKeyboardButton("⬆ Promote", callback_data=f"v2:admin:user_promote:{user['user_id']}"),
            InlineKeyboardButton("⬇ Demote", callback_data=f"v2:admin:user_demote:{user['user_id']}"),
        ],
        [
            InlineKeyboardButton("🔒 Lock Wallet", callback_data=f"v2:admin:wallet_lock:{user['user_id']}"),
            InlineKeyboardButton("🔓 Unlock Wallet", callback_data=f"v2:admin:wallet_unlock:{user['user_id']}"),
        ],
        [InlineKeyboardButton("↩ Back", callback_data="v2:admin:users")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return txt, InlineKeyboardMarkup(kb)


# ============================================================
# ADMIN — PRODUCT LIST
# ============================================================

def build_admin_product_list(products, page, total_pages):
    txt = "🛍 *All Products*\n\n"
    for p in products:
        txt += (
            f"• *{p['title']}* — ${float(p['price']):.2f}\n"
            f"ID: `{p['product_id']}` | Seller `{p['seller_id']}`\n\n"
        )

    txt += f"Page {page}/{total_pages}"

    kb = [
        [
            InlineKeyboardButton("⬅ Prev", callback_data=f"v2:admin:products_page:{page-1}"),
            InlineKeyboardButton("➡ Next", callback_data=f"v2:admin:products_page:{page+1}"),
        ],
        [InlineKeyboardButton("↩ Back", callback_data="v2:admin:panel")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return txt, InlineKeyboardMarkup(kb)


# ============================================================
# ADMIN — PRODUCT VIEW
# ============================================================

def build_admin_product_view(product):
    img = product["images"][0] if product["images"] else None
    pid = product["product_id"]

    txt = (
        f"🛍 *{product['title']}*\n"
        f"💵 ${float(product['price']):.2f}\n"
        f"📦 Stock `{product['stock_quantity']}`\n"
        f"Seller `{product['seller_id']}`\n\n"
        f"{product['description']}"
    )

    kb = [
        [InlineKeyboardButton("🗑 Delete Product", callback_data=f"v2:admin:product_delete:{pid}")],
        [InlineKeyboardButton("↩ Back", callback_data="v2:admin:products")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return {
        "photo_url": img,
        "caption": txt,
        "reply_markup": InlineKeyboardMarkup(kb)
    }


# ============================================================
# ADMIN — DISPUTES
# ============================================================

def build_admin_dispute_list(disputes):
    if not disputes:
        return (
            "⚖ No active disputes.",
            InlineKeyboardMarkup([[InlineKeyboardButton("↩ Back", callback_data="v2:admin:panel")]])
        )

    txt = "⚖ *Active Disputes*\n\n"
    for d in disputes:
        txt += (
            f"• Dispute `{d['dispute_id']}` — Order `{d['order_id']}`\n"
            f"Raised: `{d['raised_by']}`\n"
            f"Reason: {d['reason']}\n\n"
        )

    kb = [
        [InlineKeyboardButton("↩ Back", callback_data="v2:admin:panel")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return txt, InlineKeyboardMarkup(kb)
