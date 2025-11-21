# ============================================================
# modules/ui.py  —  FULL UI LAYER for Marketplace Bot V2
# Compatible with bot.py v2 + db.py v2 + Railway PostgreSQL
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
    verified = "Yes" if user["verification_status"] else "No"

    text = (
        "👋 *Marketplace Dashboard*\n\n"
        f"💰 Balance: *${balance:.2f}*\n"
        f"🧩 Role: `{role}`\n"
        f"🔒 Verified: {verified}\n"
    )

    kb = [
        [InlineKeyboardButton("🛍 Shop", callback_data="v2:shop:categories")],
        [InlineKeyboardButton("🛒 View Cart", callback_data="v2:cart:view")],
        [InlineKeyboardButton("📬 Orders", callback_data="v2:buyer:orders")],
        [InlineKeyboardButton("💼 Wallet", callback_data="v2:wallet:dashboard")],
    ]

    if role == "seller":
        kb.append([InlineKeyboardButton("📦 My Products", callback_data="v2:seller:products")])
        kb.append([InlineKeyboardButton("➕ Add Product", callback_data="v2:seller:add")])

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
    desc = product.get("description", "")
    price = float(product["price"])
    stock = product["stock_quantity"]
    category = product.get("category_name", "Unknown")

    images = product.get("images", [])
    image_url = images[0] if images else None

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
        "photo_url": image_url,
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
# CHECKOUT PAYMENT MENU
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
        "_This is a placeholder. In production, generate a SGQR._"
    )

    kb = [
        [InlineKeyboardButton("✅ I HAVE PAID", callback_data=f"v2:pay:confirm:{order_id}")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return txt, InlineKeyboardMarkup(kb)


# ============================================================
# WALLET DASHBOARD
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
# ADMIN PANEL
# ============================================================

def build_admin_panel_menu():
    txt = "🛠 *Admin Panel*\nChoose an option:"

    kb = [
        [InlineKeyboardButton("📊 System Stats", callback_data="v2:admin:stats")],
        [InlineKeyboardButton("🛍 Manage Products", callback_data="v2:admin:products")],
        [InlineKeyboardButton("👥 Manage Users", callback_data="v2:admin:users")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return txt, InlineKeyboardMarkup(kb)

# ============================================================
# SELLER — PRODUCT MANAGEMENT UI
# ============================================================

# -----------------------------------------
# Seller: Product List
# -----------------------------------------

async def build_seller_products_list(user_id, products, page, total_pages):
    if not products:
        return (
            "📦 *No products listed yet.*\nAdd your first product!",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Product", callback_data="v2:seller:add")],
                [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]
            ])
        )

    txt = "📦 *Your Products*\n\n"
    for p in products:
        txt += (
            f"*{p['title']}*\n"
            f"Price: *${float(p['price']):.2f}*\n"
            f"Stock: `{p['stock_quantity']}`\n"
            f"/ ID: `{p['product_id']}`\n\n"
        )

    txt += f"Page {page}/{total_pages}"

    kb = [
        [
            InlineKeyboardButton("⬅️ Prev", callback_data=f"v2:seller:products_page:{page-1}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"v2:seller:products_page:{page+1}")
        ],
        [InlineKeyboardButton("➕ Add Product", callback_data="v2:seller:add")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return txt, InlineKeyboardMarkup(kb)


# -----------------------------------------
# Seller — Product Detail View
# -----------------------------------------

def build_seller_product_page(product):
    pid = product["product_id"]
    title = product["title"]
    price = float(product["price"])
    stock = product["stock_quantity"]
    desc = product.get("description", "")

    img = product["images"][0] if product["images"] else None

    caption = (
        f"📦 *{title}*\n"
        f"💵 Price: *${price:.2f}*\n"
        f"📦 Stock: `{stock}`\n\n"
        f"{desc}"
    )

    kb = [
        [InlineKeyboardButton("✏️ Edit Title", callback_data=f"v2:seller:edit_title:{pid}")],
        [InlineKeyboardButton("📝 Edit Description", callback_data=f"v2:seller:edit_desc:{pid}")],
        [InlineKeyboardButton("💰 Edit Price", callback_data=f"v2:seller:edit_price:{pid}")],
        [InlineKeyboardButton("📦 Edit Stock", callback_data=f"v2:seller:edit_stock:{pid}")],
        [InlineKeyboardButton("🗑 Delete Product", callback_data=f"v2:seller:delete:{pid}")],
        [InlineKeyboardButton("↩️ Back", callback_data="v2:seller:products")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return {
        "photo_url": img,
        "caption": caption,
        "reply_markup": InlineKeyboardMarkup(kb)
    }


# -----------------------------------------
# Seller — Edit Title (Prompt UI)
# -----------------------------------------

def prompt_edit_title(pid):
    txt = (
        f"✏️ *Edit Product Title*\n\n"
        f"Product ID: `{pid}`\n"
        "Send the *new title* below:"
    )

    kb = [
        [InlineKeyboardButton("↩️ Cancel", callback_data=f"v2:seller:view:{pid}")]
    ]

    return txt, InlineKeyboardMarkup(kb)


# -----------------------------------------
# Seller — Edit Description
# -----------------------------------------

def prompt_edit_description(pid):
    txt = (
        f"📝 *Edit Description*\n\n"
        f"Product ID: `{pid}`\n"
        "Send the *new product description*:"
    )

    kb = [
        [InlineKeyboardButton("↩️ Cancel", callback_data=f"v2:seller:view:{pid}")]
    ]

    return txt, InlineKeyboardMarkup(kb)


# -----------------------------------------
# Seller — Edit Price
# -----------------------------------------

def prompt_edit_price(pid):
    txt = (
        f"💰 *Edit Price*\n\n"
        f"Product ID: `{pid}`\n"
        "Send the *new price* (numbers only):"
    )

    kb = [
        [InlineKeyboardButton("↩️ Cancel", callback_data=f"v2:seller:view:{pid}")]
    ]

    return txt, InlineKeyboardMarkup(kb)


# -----------------------------------------
# Seller — Edit Stock
# -----------------------------------------

def prompt_edit_stock(pid):
    txt = (
        f"📦 *Edit Stock Quantity*\n\n"
        f"Product ID: `{pid}`\n"
        "Send the *new stock quantity* (integer):"
    )

    kb = [
        [InlineKeyboardButton("↩️ Cancel", callback_data=f"v2:seller:view:{pid}")]
    ]

    return txt, InlineKeyboardMarkup(kb)


# -----------------------------------------
# Seller — Delete Confirmation UI
# -----------------------------------------

def build_delete_confirmation(pid):
    txt = (
        f"⚠️ *Delete Product?*\n\n"
        f"Product ID: `{pid}`\n"
        "*This action is irreversible.*"
    )

    kb = [
        [InlineKeyboardButton("🗑 Yes, Delete", callback_data=f"v2:seller:delete_confirm:{pid}")],
        [InlineKeyboardButton("↩️ Cancel", callback_data=f"v2:seller:view:{pid}")],
    ]

    return txt, InlineKeyboardMarkup(kb)


# -----------------------------------------
# Seller — Add Product (initial prompt)
# -----------------------------------------

def build_add_product_prompt():
    txt = (
        "➕ *Add New Product*\n\n"
        "Send the *product title* to begin."
    )

    kb = [
        [InlineKeyboardButton("🏠 Cancel", callback_data="v2:menu:main")]
    ]

    return txt, InlineKeyboardMarkup(kb)

# ============================================================
# ADMIN — FULL UI PANEL
# ============================================================

# -----------------------------------------
# ADMIN PANEL HOME
# -----------------------------------------

def build_admin_panel_menu():
    txt = (
        "🛠 *Admin Panel*\n\n"
        "Choose a function:"
    )
    kb = [
        [InlineKeyboardButton("📊 System Stats", callback_data="v2:admin:stats")],
        [InlineKeyboardButton("👥 Manage Users", callback_data="v2:admin:users")],
        [InlineKeyboardButton("🛍 Manage Products", callback_data="v2:admin:products")],
        [InlineKeyboardButton("⚖️ View Disputes", callback_data="v2:admin:disputes")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]
    return txt, InlineKeyboardMarkup(kb)


# -----------------------------------------
# ADMIN — SYSTEM STATS UI
# -----------------------------------------

def build_admin_stats(stats):
    txt = (
        "📊 *System Statistics*\n\n"
        f"👥 Total Users: *{stats['user_count']}*\n"
        f"🛍 Total Products: *{stats['product_count']}*\n"
        f"📦 Total Orders: *{stats['order_count']}*\n"
        f"💸 Total Payments: *{stats['payment_count']}*\n"
        f"⚖️ Active Disputes: *{stats['dispute_count']}*\n"
    )

    kb = [
        [InlineKeyboardButton("↩️ Back", callback_data="v2:admin:panel")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]
    ]

    return txt, InlineKeyboardMarkup(kb)


# -----------------------------------------
# ADMIN — USER LIST
# -----------------------------------------

async def build_admin_user_list(users, page, total_pages):
    txt = "👥 *User List*\n\n"

    for u in users:
        txt += (
            f"• @{u['username']} — `{u['role']}`\n"
            f"/ ID: `{u['user_id']}`\n"
            f"/admin user {u['user_id']}\n\n"
        )

    txt += f"Page {page}/{total_pages}"

    kb = [
        [
            InlineKeyboardButton("⬅️ Prev", callback_data=f"v2:admin:users_page:{page-1}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"v2:admin:users_page:{page+1}")
        ],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
        [InlineKeyboardButton("↩️ Back", callback_data="v2:admin:panel")],
    ]

    return txt, InlineKeyboardMarkup(kb)


# -----------------------------------------
# ADMIN — VIEW USER DETAILS
# -----------------------------------------

def build_admin_user_view(user, wallet):
    txt = (
        f"👤 *User Details*\n\n"
        f"ID: `{user['user_id']}`\n"
        f"Username: @{user['username']}\n"
        f"Role: `{user['role']}`\n"
        f"Verified: `{user['verification_status']}`\n\n"
        f"💼 Wallet:\n"
        f"Balance: *${float(wallet['balance']):.2f}*\n"
        f"Status: `{wallet['status']}`\n"
        f"Solana: `{wallet['solana_address']}`\n"
    )

    kb = [
        [
            InlineKeyboardButton("⬆ Promote", callback_data=f"v2:admin:user_promote:{user['user_id']}"),
            InlineKeyboardButton("⬇ Demote", callback_data=f"v2:admin:user_demote:{user['user_id']}")
        ],
        [
            InlineKeyboardButton("🔒 Lock Wallet", callback_data=f"v2:admin:wallet_lock:{user['user_id']}"),
            InlineKeyboardButton("🔓 Unlock Wallet", callback_data=f"v2:admin:wallet_unlock:{user['user_id']}")
        ],
        [InlineKeyboardButton("↩️ Back", callback_data="v2:admin:users")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return txt, InlineKeyboardMarkup(kb)


# -----------------------------------------
# ADMIN — PRODUCT LIST
# -----------------------------------------

def build_admin_product_list(products, page, total_pages):
    txt = "🛍 *All Products*\n\n"

    for p in products:
        txt += (
            f"*{p['title']}* — ${float(p['price']):.2f}\n"
            f"/product {p['product_id']}\n"
            f"Seller ID: `{p['seller_id']}`\n\n"
        )

    txt += f"Page {page}/{total_pages}"

    kb = [
        [
            InlineKeyboardButton("⬅️ Prev", callback_data=f"v2:admin:products_page:{page-1}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"v2:admin:products_page:{page+1}")
        ],
        [InlineKeyboardButton("↩️ Back", callback_data="v2:admin:panel")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return txt, InlineKeyboardMarkup(kb)


# -----------------------------------------
# ADMIN — PRODUCT VIEW
# -----------------------------------------

def build_admin_product_view(product):
    pid = product["product_id"]
    img = product["images"][0] if product["images"] else None

    txt = (
        f"🛍 *{product['title']}*\n\n"
        f"Price: *${float(product['price']):.2f}*\n"
        f"Stock: `{product['stock_quantity']}`\n"
        f"Status: `{product['status']}`\n"
        f"Seller ID: `{product['seller_id']}`\n\n"
        f"{product['description']}"
    )

    kb = [
        [InlineKeyboardButton("🗑 Delete Product", callback_data=f"v2:admin:product_delete:{pid}")],
        [InlineKeyboardButton("↩️ Back", callback_data="v2:admin:products")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return {"photo_url": img, "caption": txt, "reply_markup": InlineKeyboardMarkup(kb)}


# -----------------------------------------
# ADMIN — DISPUTE LIST
# -----------------------------------------

def build_admin_dispute_list(disputes):
    if not disputes:
        return (
            "⚖️ *No active disputes.*",
            InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back", callback_data="v2:admin:panel")]])
        )

    txt = "⚖️ *Active Disputes*\n\n"
    for d in disputes:
        txt += (
            f"• Dispute `{d['dispute_id']}` — Order `{d['order_id']}`\n"
            f"Raised by: `{d['raised_by']}`\n"
            f"Reason: {d['reason']}\n\n"
        )

    kb = [
        [InlineKeyboardButton("↩️ Back", callback_data="v2:admin:panel")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ]

    return txt, InlineKeyboardMarkup(kb)
