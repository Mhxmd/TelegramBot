import os
import qrcode
from io import BytesIO
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from typing import Optional
import stripe

from modules import storage, seller, chat, inventory, shopping_cart
import modules.wallet_utils as wallet

# Load .env
load_dotenv()
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
stripe.api_key = STRIPE_SECRET_KEY
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# ===========================
# BUILT-IN PRODUCTS
# ===========================
CATALOG = {
    "cat": {"name": "Cat Plush", "price": 15, "emoji": "🐱", "seller_id": 0, "desc": "Cute cat plush."},
    "hoodie": {"name": "Hoodie", "price": 30, "emoji": "🧥", "seller_id": 0, "desc": "Minimalist navy hoodie."},
    "blackcap": {"name": "Black Cap", "price": 12, "emoji": "🧢", "seller_id": 0, "desc": "Matte black cap."},
}

def clamp_qty(q): 
    return max(1, min(int(q), 99))

# ==========================================
# PRODUCT LOADING
# ==========================================
def enumerate_all_products():
    items = []
    for sku, p in CATALOG.items():
        items.append({**p, "sku": sku})

    data = storage.load_json(storage.SELLER_PRODUCTS_FILE)
    for _, plist in data.items():
        for it in plist:
            items.append(it)

    return items


def get_any_product_by_sku(sku: str):
    if sku in CATALOG:
        return CATALOG[sku]
    data = storage.load_json(storage.SELLER_PRODUCTS_FILE)
    for _, items in data.items():
        for it in items:
            if it.get("sku") == sku:
                return it
    return None


# ==========================================
# SEARCH
# ==========================================
def search_products_by_name(query: str):
    query = query.lower().strip()
    results = []
    for it in enumerate_all_products():
        if query in it.get("name", "").lower():
            results.append(it)
    return results


async def ask_user_search(update, context):
    q = update.callback_query
    context.user_data["awaiting_search"] = "users"

    await q.edit_message_text(
        "👤 *Search Users*\n\nSend a *username* or *user ID*.",
        parse_mode="Markdown",
    )


async def ask_search(update, context):
    q = update.callback_query
    context.user_data["awaiting_search"] = "products"

    await q.edit_message_text(
        "🔍 *Search Products*\n\nSend a product name.",
        parse_mode="Markdown",
    )


async def show_user_search_results(update, context, results):
    msg = update.effective_message

    if not results:
        return await msg.reply_text("No users found.")

    blocks = []
    buttons = []

    for u in results:
        uid = int(u["user_id"])
        uname = u.get("username") or "unknown"
        role = u.get("role", "buyer")

        items = storage.list_seller_products(uid)

        if items:
            item_lines = []
            for it in items[:5]:
                name = it.get("name", "Unnamed")
                price = float(it.get("price", 0))
                item_lines.append(f"• {name} — ${price:.2f}")
            selling = "Items selling:\n" + "\n".join(item_lines)
        else:
            selling = "Items selling:\n• None"

        blocks.append(
            f"👤 `{uid}` — @{uname} ({role})\n\n{selling}"
        )

        buttons.append([
            InlineKeyboardButton("💬 Message", callback_data=f"chat:user:{uid}")
        ])

    buttons.append([InlineKeyboardButton("🏠 Home", callback_data="menu:main")])

    await msg.reply_text(
        "👤 *User Search Results*\n\n" + "\n\n".join(blocks),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


# ==========================================
# MAIN MENU
# ==========================================
def build_main_menu(balance: float, uid: int = None):
    cart_count = 0
    if uid:
        cart = shopping_cart.get_user_cart(uid)
        cart_count = sum(item["qty"] for item in cart.values())

    cart_label = f"🛒 Cart ({cart_count})"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍 Marketplace", callback_data="menu:shop"),
         InlineKeyboardButton("📦 Orders", callback_data="menu:orders")],
        [InlineKeyboardButton(cart_label, callback_data="cart:view"),
         InlineKeyboardButton("💼 Wallet", callback_data="menu:wallet")],
        [InlineKeyboardButton("🛠 Sell", callback_data="menu:sell"),
         InlineKeyboardButton("✉ Messages", callback_data="menu:messages")],
        [InlineKeyboardButton("💬 Lounge", callback_data="chat:public_open"),
         InlineKeyboardButton("⚙ Functions", callback_data="menu:functions")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="menu:refresh")],
    ])

    text = (
        "🌀 *Xchange — Secure Escrow Marketplace*\n"
        "══════════════════════\n"
        f"💳 *Balance:* `${balance:.2f}`\n"
        "══════════════════════\n"
        "_Buy • Sell • Escrow • Trade Safely_\n"
    )
    return kb, text




# ==========================================
# SHOP PAGE
# ==========================================
def build_shop_keyboard(uid=None):
    items = enumerate_all_products()
    cart = shopping_cart.get_user_cart(uid) if uid else {}

    rows = []
    display_lines = []

    for it in items:
        sku = it["sku"]
        price = float(it["price"])
        avail = inventory.get_available_stock(sku)

        if avail is None:
            stock_label = "♾ Unlimited"
        elif avail <= 0:
            stock_label = "❌ Out of stock"
        else:
            stock_label = f"📦 Stock: {avail}"

        display_lines.append(
            f"{it.get('emoji','🛍')} *{it['name']}* — `${price:.2f}`\n{stock_label}"
        )

        disabled = avail == 0
        rows.append([
            InlineKeyboardButton(
                f"💰 Buy ${price:.2f}",
                callback_data=f"buy:{sku}:1" if not disabled else "noop"
            ),
            InlineKeyboardButton(
                "🛒 Add to Cart",
                callback_data=f"cart:add:{sku}" if not disabled else "noop"
            ),
            InlineKeyboardButton(
                "💬 Contact Seller",
                callback_data=f"contact:{sku}:{it.get('seller_id',0)}"
            ),
        ])

    rows += [
        [InlineKeyboardButton("🔍 Search Items", callback_data="shop:search")],
        [InlineKeyboardButton("👤 Search Users", callback_data="search:users")],
        [InlineKeyboardButton("🛒 Go to Cart", callback_data="cart:view")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")]
    ]

    return (
        "🛍 **Xchange Marketplace**\n\n" + "\n\n".join(display_lines),
        InlineKeyboardMarkup(rows)
    )


# ==========================================
# BUY & CHECKOUT
# ==========================================
async def on_buy(update, context, sku, qty):
    q = update.callback_query
    qty = clamp_qty(qty)

    ok, msg = inventory.check_available(sku, qty)
    if not ok:
        return await q.answer(msg, show_alert=True)

    item = get_any_product_by_sku(sku)
    total = float(item["price"]) * qty

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Stripe", callback_data=f"stripe:{sku}:{qty}")],
        [InlineKeyboardButton("🇸🇬 PayNow", callback_data=f"hitpay:{sku}:{qty}")],
        [InlineKeyboardButton("🪙 Crypto (SOL)", callback_data=f"crypto:{sku}:{qty}")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu:shop")],
    ])

    await q.edit_message_text(
        f"*{item['name']}*\nQty: {qty}\nTotal: `${total:.2f}`\n\nChoose payment:",
        reply_markup=kb,
        parse_mode="Markdown",
    )

# ==========================================
# SELLER MENU 
# ==========================================
def build_seller_menu(role: str):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Listing", callback_data="sell:add")],
        [InlineKeyboardButton("📋 My Listings", callback_data="sell:list")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
    ])

    text = (
        "🛠 *Seller Panel*\n"
        "══════════════════════\n"
        "Manage your product listings.\n"
        "_Add, edit, or remove items._"
    )
    return text, kb

# ==========================================
# SHOW SELLER LISTINGS
# ==========================================
async def show_seller_listings(update, context):
    q = update.callback_query
    uid = update.effective_user.id

    listings = storage.list_seller_products(uid)

    if not listings:
        return await q.edit_message_text(
            "📋 *My Listings*\n\n_No active listings._",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Add Listing", callback_data="sell:add")],
                [InlineKeyboardButton("🏠 Home", callback_data="menu:main")]
            ]),
            parse_mode="Markdown",
        )

    lines = ["📋 *My Listings*"]
    buttons = []

    for it in listings:
        sku = it.get("sku")
        name = it.get("name")
        price = float(it.get("price", 0))
        stock = int(item.get("stock", 0))
        if stock < qty:
             return await q.answer("❌ Not enough stock available.", show_alert=True)


        lines.append(f"\n• *{name}* — `${price:.2f}` (Stock: {stock})")
        buttons.append([
            InlineKeyboardButton("❌ Remove", callback_data=f"sell:remove_confirm:{sku}")
        ])

    buttons.append([InlineKeyboardButton("🏠 Home", callback_data="menu:main")])

    await q.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )

# ==========================================
# CONFIRM REMOVE LISTING
# ==========================================
async def confirm_remove_listing(update, context, sku):
    q = update.callback_query

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, Remove", callback_data=f"sell:remove_do:{sku}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="sell:list")],
    ])

    await q.edit_message_text(
        "⚠️ *Remove Listing?*\nThis action cannot be undone.",
        reply_markup=kb,
        parse_mode="Markdown",
    )


async def do_remove_listing(update, context, sku):
    q = update.callback_query
    uid = update.effective_user.id

    ok = storage.remove_seller_product(uid, sku)

    msg = "✅ Listing removed." if ok else "❌ Failed to remove listing."

    await q.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 My Listings", callback_data="sell:list")],
            [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
        ]),
        parse_mode="Markdown",
    )

# ==========================================
# ADD LISTING FLOW (UI)
# ==========================================
async def ask_add_listing(update, context):
    q = update.callback_query
    context.user_data["sell_flow"] = {"step": "name"}

    await q.edit_message_text(
        "➕ *Add Listing*\n\nSend the *product name:*",
        parse_mode="Markdown",
    )


# ==========================================
#Cart Checkout
# ==========================================

# ==========================================
# CART CHECKOUT (ALL ITEMS)
# ==========================================
async def cart_checkout_all(update, context):
    q = update.callback_query
    uid = update.effective_user.id

    cart = shopping_cart.get_user_cart(uid)
    if not cart:
        return await q.answer("Your cart is empty.", show_alert=True)

    total = sum(item["price"] * item["qty"] for item in cart.values())

    txt = (
        "🧾 *Cart Checkout*\n\n"
        f"• Total: *${total:.2f}*\n\n"
        "_Choose payment method:_"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Stripe", callback_data=f"stripe_cart:{total}")],
        [InlineKeyboardButton("🇸🇬 PayNow (HitPay)", callback_data=f"hitpay_cart:{total}")],
        [InlineKeyboardButton("🟦 NETS", callback_data=f"nets_cart:{total}")],
        [InlineKeyboardButton("🔗 Crypto (SOL)", callback_data=f"crypto_cart:{total}")],
        [InlineKeyboardButton("🔙 Back", callback_data="cart:view")],
    ])

    return await q.edit_message_text(txt, parse_mode="Markdown", reply_markup=kb)


#Crypto Checkout

async def crypto_checkout(update, context, sku, qty):
    q = update.callback_query
    buyer_id = update.effective_user.id
    item = get_any_product_by_sku(sku)
    qty = clamp_qty(qty)

    SOL_USD_RATE = 100.0  # PoC rate
    total_usd = float(item["price"]) * qty
    total_sol = total_usd / SOL_USD_RATE

    buyer_wallet = wallet.ensure_user_wallet(buyer_id)
    escrow_wallet = wallet.ensure_user_wallet(ADMIN_ID)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm Crypto Payment",
            callback_data=f"crypto_confirm:{sku}:{qty}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu:shop")],
    ])

    await q.edit_message_text(
        "🪙 *Crypto Checkout (SOL)*\n\n"
        f"Amount: `{total_sol:.4f} SOL`\n"
        "Funds will be held in escrow.",
        reply_markup=kb,
        parse_mode="Markdown",
    )

# ==========================================
# CRYPTO CART CHECKOUT (SOL — PoC)
# ==========================================
async def crypto_checkout(update, context, sku, qty):
    q = update.callback_query
    qty = clamp_qty(qty)

    item = get_any_product_by_sku(sku)
    total_usd = float(item["price"]) * qty
    SOL_RATE = 100.0
    total_sol = total_usd / SOL_RATE

    escrow = wallet.ensure_user_wallet(ADMIN_ID)["public_key"]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I Have Paid", callback_data=f"crypto_confirm:{sku}:{qty}")],
        [InlineKeyboardButton(
            "🔍 View Escrow (Devnet)",
            url=f"https://solscan.io/account/{escrow}?cluster=devnet"
        )],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu:shop")],
    ])

    await q.edit_message_text(
        "🪙 *Crypto Checkout (SOL)*\n\n"
        f"Send `{total_sol:.4f} SOL`\n"
        f"To escrow:\n`{escrow}`\n\n"
        "_Funds held until delivery._",
        reply_markup=kb,
        parse_mode="Markdown",
    )
# ==========================================
# CRYPTO PAYMENT CONFIRMATION


async def crypto_confirm(update, context, sku, qty):
    q = update.callback_query
    buyer = update.effective_user.id
    qty = clamp_qty(qty)

    item = get_any_product_by_sku(sku)
    total = float(item["price"]) * qty

    order_id = storage.add_order(
        buyer,
        item["name"],
        qty,
        total,
        "Crypto (SOL)",
        int(item.get("seller_id", 0)),
    )

    ok, msg = inventory.reserve_for_payment(order_id, sku, qty)
    if not ok:
        return await q.edit_message_text(f"❌ {msg}")

    await q.edit_message_text(
        "✅ *Payment marked as sent.*\n"
        "🔒 Stock reserved\n"
        "📦 Seller notified\n"
        "🛡 Escrow active",
        parse_mode="Markdown",
    )



# ==========================================
# MENU ROUTER
# ==========================================
async def on_menu(update, context):
    q = update.callback_query
    _, tab = q.data.split(":", 1)
    uid = update.effective_user.id

    async def safe_edit(text, kb):
        try:
            return await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        except:
            return await context.bot.send_message(uid, text, reply_markup=kb, parse_mode="Markdown")

    #  handle the Home and Refresh buttons
    if tab in ["main", "refresh"]:
        balance = storage.get_balance(uid)
        kb, text = build_main_menu(balance, uid)
        return await safe_edit(text, kb)

    if tab == "shop":
        txt, kb = build_shop_keyboard(uid)
        return await safe_edit(txt, kb)

    if tab == "cart":
        return await shopping_cart.view_cart(update, context)

    if tab == "wallet":
        bal = storage.get_balance(uid)
        wallet_data = wallet.ensure_user_wallet(uid)
        pub = wallet_data["public_key"]

        sol_bal = wallet.get_balance_both(pub)

        text = (
            "💼 **Wallet (PoC)**\n"
            "══════════════════════\n"
            f"💳 *Fiat Balance:* `${bal:.2f}`\n\n"
            f"🔗 *Solana Address:*\n`{pub}`\n\n"
            f"🧪 *Devnet SOL:* `{sol_bal['devnet']:.4f}`\n"
            f"🌍 *Mainnet SOL:* `{sol_bal['mainnet']:.4f}`\n"  # Make sure this says 'mainnet'
            "══════════════════════\n"
            "_Devnet shown for proof-of-concept only._"
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Deposit (SOL)", callback_data="wallet:deposit")],
            [InlineKeyboardButton("📤 Withdraw (SOL)", callback_data="wallet:withdraw")],
            [InlineKeyboardButton("🔗 View on Solscan (Devnet)",
                url=f"https://solscan.io/account/{pub}?cluster=devnet")],
            [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
        ])

        return await safe_edit(text, kb)


    if tab == "messages":
        threads = storage.load_json(storage.MESSAGES_FILE)
        buttons = [
            [InlineKeyboardButton(f"💬 {v['product']['name']}", callback_data=f"chat:open:{k}")]
            for k, v in threads.items()
            if uid in (v.get("buyer_id"), v.get("seller_id"))
        ]
        buttons.append([InlineKeyboardButton("🏠 Home", callback_data="menu:main")])
        return await safe_edit("💌 *Messages*", InlineKeyboardMarkup(buttons))

    if tab == "orders":
        storage.expire_stale_pending_orders(grace_seconds=900)
        orders = storage.list_orders_for_user(uid)

        if not orders:
            txt = "📦 *Orders*\n\nNo orders yet."
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="menu:main")]])
            return await safe_edit(txt, kb)

        orders = sorted(orders, key=lambda o: int(o.get("ts", 0)), reverse=True)

        lines = ["📦 *Orders*"]
        buttons = []

        for o in orders[:20]:
            oid = o.get("id", "unknown")
            item = o.get("item", "item")
            qty = o.get("qty", 1)
            amt = float(o.get("amount", 0))
            status = str(o.get("status", "pending")).lower()
            method = o.get("method", "-")

            lines.append(f"\n• `{oid}`")
            lines.append(f"  {item} x{qty}  `${amt:.2f}`")
            lines.append(f"  Status: *{status}*  Method: {method}")

            if oid != "unknown" and status in ("pending", "awaiting_payment", "created"):
                buttons.append([
                    InlineKeyboardButton(f"❌ Cancel {oid}", callback_data=f"ordercancel:{oid}")
                ])

            if oid != "unknown":
                buttons.append([
                    InlineKeyboardButton(f"🗄 Archive {oid}", callback_data=f"orderarchive:{oid}")
                ])

        lines.append("")
        buttons.append([InlineKeyboardButton("🧹 Unarchive all", callback_data="orderunarchiveall")])
        buttons.append([InlineKeyboardButton("🏠 Home", callback_data="menu:main")])

        return await safe_edit("\n".join(lines), InlineKeyboardMarkup(buttons))

    # ==========================
    # SELL MENU
    # ==========================
    if tab == "sell":
        # Admin bypass
        if uid == ADMIN_ID:
            txt, kb = seller.build_seller_menu("seller")
            return await safe_edit(txt, kb)

        role = storage.get_role(uid)

        # Buyer → apply seller
        if role != "seller":
            return await safe_edit(
                "🛠 *Become a Seller*\n\n"
                "To sell items, please verify that you are human.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Start Verification", callback_data="seller:apply")],
                    [InlineKeyboardButton("🏠 Home", callback_data="menu:main")]
                ])
            )

        status = storage.get_seller_status(uid)

        # Needs captcha
        if status == "pending_captcha":
            question, answer = seller.generate_captcha()
            storage.user_flow_state[uid] = {
                "phase": "captcha",
                "answer": answer
            }
            return await safe_edit(
                f"🧠 *Human Verification*\n\nSolve:\n*{question}*",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Cancel", callback_data="menu:main")]
                ])
            )

        # Passed captcha but awaiting trust
        if status == "human_verified":
            return await safe_edit(
                "⏳ *Seller Pending*\n\n"
                "Your account is verified as human.\n"
                "Complete your first successful order to unlock selling.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Home", callback_data="menu:main")]
                ])
            )

        # Fully verified seller
        txt, kb = seller.build_seller_menu("seller")
        return await safe_edit(txt, kb)


    # ==========================
    # FUNCTIONS (ADMIN ONLY)
    # ==========================
    if tab == "functions":
        if uid != ADMIN_ID:
            return await safe_edit(
                "⚙️ *Functions Panel*\n\n"
                "❌ Access denied.",
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 Home", callback_data="menu:main")]
                ])
            )

        return await show_functions_menu(update, context)

# ==========================================
# FUNCTIONS PANEL
# ==========================================
async def show_functions_menu(update, context):
    q = update.callback_query

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Disputes (Admin)", callback_data="admin:disputes")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")],
    ])

    return await q.edit_message_text(
        "⚙️ *Functions Panel*\nAdmin tools + utilities.",
        reply_markup=kb,
        parse_mode="Markdown",
    )
