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
        price = it["price"]
        qty_in_cart = cart.get(sku, {}).get("qty", 0)

        display_lines.append(
            f"{it.get('emoji','🛍')} *{it['name']}* — `${price:.2f}`"
        )

        if qty_in_cart > 0:
            cart_btn = InlineKeyboardButton(
                f"🛒 Add to Cart ({qty_in_cart})",
                callback_data=f"cart:add:{sku}"
            )
        else:
            cart_btn = InlineKeyboardButton(
                "🛒 Add to Cart",
                callback_data=f"cart:add:{sku}"
            )

        rows.append([
            InlineKeyboardButton(f"💰 Buy ${price:.2f}", callback_data=f"buy:{sku}:1"),
            cart_btn,
            InlineKeyboardButton("💬 Contact Seller", callback_data=f"contact:{sku}:{it.get('seller_id',0)}"),
        ])

    rows.append([InlineKeyboardButton("🔍 Search Items", callback_data="shop:search")])
    rows.append([InlineKeyboardButton("👤 Search Users", callback_data="search:users")])
    rows.append([InlineKeyboardButton("🛒 Go to Cart", callback_data="cart:view")])
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="menu:main")])

    txt = (
        "🛍 **Xchange Marketplace**\nBrowse products or list your own.\n\n"
        + ("\n".join(display_lines) if display_lines else "_No items yet._")
    )
    return txt, InlineKeyboardMarkup(rows)

# ==========================================
# BUY & CHECKOUT
# ==========================================
async def on_buy(update, context, sku, qty):
    q = update.callback_query
    item = get_any_product_by_sku(sku)
    qty = clamp_qty(qty)

    if not item:
        return await q.answer("Item not found", show_alert=True)

    total = float(item["price"]) * qty

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Stripe", callback_data=f"stripe:{sku}:{qty}")],
        [InlineKeyboardButton("🇸🇬 PayNow (HitPay)", callback_data=f"hitpay:{sku}:{qty}")],
        [InlineKeyboardButton("🟦 NETS", callback_data=f"nets:{sku}:{qty}")],
        [InlineKeyboardButton("🪙 Crypto (SOL)", callback_data=f"crypto:{sku}:{qty}")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu:shop")],
    ])

    await q.edit_message_text(
        f"*{item['name']}*\n"
        f"Qty: {qty}\n"
        f"Total: ${total:.2f}\n\n"
        "_Choose payment method:_",
        reply_markup=kb,
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
async def crypto_cart_checkout(update, context, total: float):
    q = update.callback_query
    uid = update.effective_user.id

    # Seller escrow wallet (PoC: platform wallet)
    escrow_wallet = wallet.ensure_user_wallet(0)["public_key"]

    text = (
        "🔗 *Crypto Checkout (SOL)*\n"
        "══════════════════════\n"
        f"🧾 *Order Total:* `${total:.2f}`\n\n"
        "📥 *Send SOL to Escrow Address:*\n"
        f"`{escrow_wallet}`\n\n"
        "⚠️ *Important*\n"
        "• Devnet only (PoC)\n"
        "• Funds held in escrow\n"
        "• Admin releases on delivery\n\n"
        "_After sending, click **I Have Paid**_"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I Have Paid", callback_data=f"crypto_confirm:{total}")],
        [InlineKeyboardButton(
            "🔍 View Escrow (Devnet)",
            url=f"https://solscan.io/account/{escrow_wallet}?cluster=devnet"
        )],
        [InlineKeyboardButton("❌ Cancel", callback_data="cart:view")],
    ])

    return await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")



async def crypto_confirm(update, context, sku, qty):
    q = update.callback_query
    buyer_id = update.effective_user.id
    item = get_any_product_by_sku(sku)
    qty = clamp_qty(qty)

    SOL_USD_RATE = 100.0
    total_usd = float(item["price"]) * qty
    total_sol = total_usd / SOL_USD_RATE

    buyer_wallet = wallet.ensure_user_wallet(buyer_id)
    escrow_wallet = wallet.ensure_user_wallet(ADMIN_ID)

    result = wallet.send_sol(
        buyer_wallet["private_key"],
        escrow_wallet["public_key"],
        total_sol,
    )

    if isinstance(result, dict) and "error" in result:
        return await q.edit_message_text(f"❌ Crypto failed:\n{result['error']}")

    storage.add_order(
        buyer_id,
        item["name"],
        qty,
        total_usd,
        "Crypto (SOL)",
        int(item.get("seller_id", 0)),
    )

    await q.edit_message_text(
        "✅ *Crypto payment successful!*\n"
        "Funds are held in escrow.",
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
            f"🧪 *Testnet SOL:* `{sol_bal['testnet']:.4f}`\n"
            "══════════════════════\n"
            "_Devnet/Testnet shown for proof-of-concept only._"
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

    if tab == "sell":
        txt, kb = seller.build_seller_menu(storage.get_role(uid))
        return await safe_edit(txt, kb)

    if tab == "functions":
        return await show_functions_menu(update, context)

    if tab in ("main", "refresh"):
        kb, txt = build_main_menu(storage.get_balance(uid), uid)
        return await safe_edit(txt, kb)


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
