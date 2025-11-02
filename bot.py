# ==========================
# TELEGRAM MARKETPLACE BOT – BUYER + SELLER + CHAT RELAY + PUBLIC CHAT
# (Button-based chat init: “💬 Contact Seller”)
#
# Features:
# - Main menu: Shop, Sell, Orders, Wallet, Settings, Help
# - EXTRA: 🗣 Public Chat (global room, everyone sees messages)
# - EXTRA: ✉️ Messages (your private buyer–seller chats)
# - EXTRA: 📘 Functions (quick help / feature list)
# - Products: built-ins + seller-added listings
# - Buyer checkout: Stripe (card), PayNow QR (mock)
# - Wallet balances persisted (balances.json)
# - Solana wallet auto-created per user (wallets.json)
# - Orders persisted (orders.json)
# - Sellers: register, add listings (guided), my listings
# - Buyer–Seller chat: “Contact Seller” → “Open Chat”, relay messages
# - Message log (messages.json)
# - Public chat log (public_chat.json)
#
# Files auto-created if missing:
# - balances.json, orders.json, roles.json, seller_products.json, messages.json, wallets.json, public_chat.json
#
# Requirements:
# pip install python-telegram-bot==21.* python-dotenv qrcode pillow stripe
# (and your existing solana deps for wallet_utils)
#
# Create .env with BOT_TOKEN, STRIPE_SECRET_KEY (and optional ADMIN_ID)
# ==========================

import os
import time
import json
import logging
import stripe
from io import BytesIO
from dotenv import load_dotenv
import qrcode

# ==========================
# NEW: Solana wallet imports
# ==========================
from wallet_utils import create_wallet, send_sol  # individual Solana wallets

from telegram import (
    Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ==========================
# CONFIG & KEYS (.env)
# ==========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()

stripe.api_key = STRIPE_SECRET_KEY

# ==========================
# RUNTIME STATE (in-memory)
# ==========================
last_message_time: dict[int, float] = {}       # anti-spam
user_flow_state: dict[int, dict] = {}          # seller listing flow, send-SOL flow, etc.
active_chats: dict[int, str] = {}              # user_id -> private chat thread_id
active_public_chat: dict[int, bool] = {}       # user_id -> True if he's typing in public chat

# ==========================
# PERSISTENT JSON FILES
# ==========================
BALANCES_FILE = "balances.json"
ORDERS_FILE = "orders.json"
ROLES_FILE = "roles.json"
SELLER_PRODUCTS_FILE = "seller_products.json"
MESSAGES_FILE = "messages.json"          # private 1-1 chats (buyer-seller)
WALLETS_FILE = "wallets.json"
PUBLIC_CHAT_FILE = "public_chat.json"    # global room history

for path, default in [
    (BALANCES_FILE, {}),
    (ORDERS_FILE, {}),
    (ROLES_FILE, {}),
    (SELLER_PRODUCTS_FILE, {}),
    (MESSAGES_FILE, {}),
    (WALLETS_FILE, {}),
    (PUBLIC_CHAT_FILE, []),  # list of {user_id, username, text, ts}
]:
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f, indent=2)

# Built-in catalog (admin/house listings). Sellers add more via UI.
CATALOG = {
    "cat": {"name": "Cat", "price": 15, "emoji": "🐱", "seller_id": 0, "desc": "Cute cat plush."},
    "hoodie": {"name": "Hoodie", "price": 30, "emoji": "🧥", "seller_id": 0, "desc": "Comfy cotton hoodie."},
    "blackcap": {"name": "Black Cap", "price": 12, "emoji": "🧢", "seller_id": 0, "desc": "Minimalist black cap."},
}

# ==========================
# LOGGING
# ==========================
logging.basicConfig(
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("marketbot")

# ==========================
# JSON HELPERS
# ==========================
def load_json(path: str):
    with open(path, "r") as f:
        return json.load(f)

def save_json(path: str, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# ==========================
# SOLANA WALLET HELPERS
# ==========================
def get_user_wallet(user_id: int) -> dict:
    wallets = load_json(WALLETS_FILE)
    uid = str(user_id)
    if uid not in wallets:
        w = create_wallet()
        wallets[uid] = {
            "public_key": w["public_key"],
            "private_key": w["private_key"],
            "created_ts": int(time.time())
        }
        save_json(WALLETS_FILE, wallets)
        logger.info(f"Created new Solana wallet for {user_id}: {w['public_key']}")
    return wallets[uid]

# ==========================
# BALANCE & ORDER HELPERS
# ==========================
def get_balance(user_id: int) -> float:
    data = load_json(BALANCES_FILE)
    return float(data.get(str(user_id), 0.0))

def set_balance(user_id: int, value: float):
    data = load_json(BALANCES_FILE)
    data[str(user_id)] = round(float(value), 2)
    save_json(BALANCES_FILE, data)

def update_balance(user_id: int, delta: float):
    set_balance(user_id, get_balance(user_id) + float(delta))

def add_order(user_id: int, item_name: str, qty: int, amount: float, method: str, seller_id: int):
    orders = load_json(ORDERS_FILE)
    order = {
        "item": item_name,
        "qty": int(qty),
        "amount": float(amount),
        "method": method,
        "seller_id": seller_id,
        "status": "Pending Payment",
        "ts": int(time.time()),
    }
    orders.setdefault(str(user_id), []).append(order)
    save_json(ORDERS_FILE, orders)

def list_orders(user_id: int):
    orders = load_json(ORDERS_FILE)
    return orders.get(str(user_id), [])

# ==========================
# ROLE HELPERS
# ==========================
def get_role(user_id: int) -> str:
    roles = load_json(ROLES_FILE)
    return roles.get(str(user_id), "buyer")

def set_role(user_id: int, role: str):
    roles = load_json(ROLES_FILE)
    roles[str(user_id)] = role
    save_json(ROLES_FILE, roles)

# ==========================
# SELLER PRODUCT HELPERS
# ==========================
def list_seller_products(seller_id: int):
    data = load_json(SELLER_PRODUCTS_FILE)
    return data.get(str(seller_id), [])

def add_seller_product(seller_id: int, title: str, price: float, desc: str):
    data = load_json(SELLER_PRODUCTS_FILE)
    products = data.get(str(seller_id), [])
    sku = f"u{seller_id}_{int(time.time())}"
    products.append({
        "sku": sku,
        "name": title,
        "price": float(price),
        "emoji": "🛒",
        "seller_id": seller_id,
        "desc": desc,
    })
    data[str(seller_id)] = products
    save_json(SELLER_PRODUCTS_FILE, data)
    return sku

def get_any_product_by_sku(sku: str):
    if sku in CATALOG:
        return CATALOG[sku]
    data = load_json(SELLER_PRODUCTS_FILE)
    for sid, items in data.items():
        for it in items:
            if it["sku"] == sku:
                return it
    return None

def enumerate_all_products():
    items = []
    for sku, p in CATALOG.items():
        items.append({**p, "sku": sku})
    data = load_json(SELLER_PRODUCTS_FILE)
    for sid, plist in data.items():
        for it in plist:
            items.append(it)
    return items

# ==========================
# PRIVATE CHAT (buyer–seller) HELPERS
# ==========================
def new_chat_thread(buyer_id: int, seller_id: int, product):
    threads = load_json(MESSAGES_FILE)
    thread_id = f"t_{int(time.time())}_{buyer_id}_{seller_id}"
    threads[thread_id] = {
        "buyer_id": buyer_id,
        "seller_id": seller_id,
        "product": {
            "sku": product.get("sku"),
            "name": product.get("name"),
            "price": product.get("price"),
        },
        "messages": [],
        "last_ts": int(time.time()),
    }
    save_json(MESSAGES_FILE, threads)
    return thread_id

def append_chat_message(thread_id: str, from_user: int, text: str):
    threads = load_json(MESSAGES_FILE)
    if thread_id not in threads:
        return
    threads[thread_id]["messages"].append({
        "from": int(from_user),
        "text": text,
        "ts": int(time.time())
    })
    threads[thread_id]["last_ts"] = int(time.time())
    save_json(MESSAGES_FILE, threads)

def get_thread(thread_id: str):
    threads = load_json(MESSAGES_FILE)
    return threads.get(thread_id)

def list_user_threads(user_id: int):
    """Return list of threads where user_id is buyer or seller, newest first, safe sorting."""
    threads = load_json(MESSAGES_FILE)
    out = []
    for tid, th in threads.items():
        if th.get("buyer_id") == user_id or th.get("seller_id") == user_id:
            last_ts = th.get("last_ts")
            if last_ts is None:
                # fallback to last message ts
                if th.get("messages"):
                    last_ts = th["messages"][-1].get("ts", 0)
                else:
                    last_ts = 0
            out.append((tid, th, int(last_ts)))
    # safe sort
    out.sort(key=lambda x: x[2], reverse=True)
    return out

# ==========================
# PUBLIC CHAT HELPERS
# ==========================
def add_public_message(user_id: int, username: str, text: str):
    msgs = load_json(PUBLIC_CHAT_FILE)
    msgs.append({
        "user_id": user_id,
        "username": username or f"user_{user_id}",
        "text": text,
        "ts": int(time.time())
    })
    # keep last 100 msgs to avoid giant file
    msgs = msgs[-100:]
    save_json(PUBLIC_CHAT_FILE, msgs)

def render_public_messages(limit: int = 15) -> str:
    msgs = load_json(PUBLIC_CHAT_FILE)
    if not msgs:
        return "🗣 *Public Chat* is empty.\nSay something!"
    parts = []
    for m in msgs[-limit:]:
        uname = m.get("username") or f"user_{m.get('user_id')}"
        parts.append(f"• *{uname}*: {m.get('text')}")
    return "🗣 *Public Chat (Global Feed)*\n" + "\n".join(parts)

# ==========================
# UTIL HELPERS
# ==========================
def is_spamming(user_id: int, cooldown: float = 1.25) -> bool:
    now = time.time()
    last = last_message_time.get(user_id, 0)
    if (now - last) < cooldown:
        return True
    last_message_time[user_id] = now
    return False

def generate_paynow_qr(amount: float, name="TestBotShop") -> BytesIO:
    data = f"PayNow to {name} - Amount: ${amount:.2f}"
    img = qrcode.make(data)
    bio = BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return bio

def clamp_qty(qty: int) -> int:
    return max(1, min(int(qty), 99))

# ==========================
# UI BUILDERS
# ==========================
def build_main_menu(balance: float) -> tuple[InlineKeyboardMarkup, str]:
    buttons = [
        [InlineKeyboardButton("🛍️ Shop", callback_data="menu:shop"),
         InlineKeyboardButton("📦 Orders", callback_data="menu:orders")],
        [InlineKeyboardButton("💼 Wallet", callback_data="menu:wallet"),
         InlineKeyboardButton("🛠 Sell", callback_data="menu:sell")],
        [InlineKeyboardButton("🗣 Public Chat", callback_data="menu:public"),
         InlineKeyboardButton("✉️ Messages", callback_data="menu:messages")],
        [InlineKeyboardButton("📘 Functions", callback_data="menu:functions"),
         InlineKeyboardButton("💬 Help", callback_data="menu:help")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="menu:refresh")],
    ]
    text = (
        "👋 *Welcome to Telegram Marketplace!*\n\n"
        f"💰 Balance: *${balance:.2f}*\n—\n"
        "Use the buttons below to browse items, manage orders, wallet, chat with sellers, or join the public chat."
    )
    return InlineKeyboardMarkup(buttons), text

def build_shop_keyboard():
    items = enumerate_all_products()
    lines = []
    rows = []
    for it in items:
        price = it["price"]
        name = it["name"]
        emoji = it.get("emoji", "🛒")
        sku = it.get("sku")
        seller_id = it.get("seller_id", 0)
        lines.append(f"{emoji} *{name}* — ${price:.2f}")
        rows.append([
            InlineKeyboardButton(f"Buy ${price:.2f}", callback_data=f"buy:{sku}:1"),
            InlineKeyboardButton("💬 Contact Seller", callback_data=f"contact:{sku}:{seller_id}")
        ])
    if not lines:
        text = "🛍️ *Our Products*\n\nNo items yet."
    else:
        text = "🛍️ *Our Products*\n\n" + "\n".join(lines) + "\n\nTap a button below:"
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])
    return text, InlineKeyboardMarkup(rows)

def build_seller_menu(role: str) -> tuple[str, InlineKeyboardMarkup]:
    if role != "seller":
        text = (
            "🛠 *Seller Center*\n\n"
            "You’re currently a *buyer*. Become a seller to list items."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Register as Seller", callback_data="sell:register")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
        ])
    else:
        text = (
            "🛠 *Seller Center*\n\n"
            "Manage your listings below."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add Listing", callback_data="sell:add")],
            [InlineKeyboardButton("📄 My Listings", callback_data="sell:list")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
        ])
    return text, kb

# ==========================
# COMMANDS
# ==========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_spamming(user_id):
        return
    _ = get_user_wallet(user_id)  # ensure Solana wallet
    kb, text = build_main_menu(get_balance(user_id))
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

async def shop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_spamming(user_id):
        return
    text, kb = build_shop_keyboard()
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

# ==========================
# MENU NAVIGATION
# ==========================
async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = update.effective_user.id
    _, choice = (q.data or "menu:").split(":", 1)

    if choice == "shop":
        text, kb = build_shop_keyboard()
        await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    elif choice == "orders":
        orders = list_orders(user_id)
        if not orders:
            out = "📦 *Your Orders*\n\nNo orders yet."
        else:
            lines = []
            for o in orders:
                lines.append(f"• {o['item']} ×{o['qty']} — ${o['amount']:.2f} ({o['status']})")
            out = "📦 *Your Orders*\n\n" + "\n".join(lines)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]])
        await q.edit_message_text(out, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    elif choice == "wallet":
        bal = get_balance(user_id)
        sol_wallet = get_user_wallet(user_id)
        pub = sol_wallet["public_key"]
        out = (
            f"💼 *Wallet*\n\n"
            f"Fiat Balance: *${bal:.2f}*\n"
            f"Solana Deposit Address:\n`{pub}`\n\n"
            f"Use the buttons below to view/copy your deposit address."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Show Deposit Address (SOL)", callback_data="wallet:show_sol")],
            [InlineKeyboardButton("📤 Send SOL (placeholder)", callback_data="wallet:send_sol")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
        ])
        await q.edit_message_text(out, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    elif choice == "sell":
        role = get_role(user_id)
        text, kb = build_seller_menu(role)
        await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    elif choice == "public":
        # turn on public mode for this user
        active_public_chat[user_id] = True
        # also exit private chat if any
        active_chats.pop(user_id, None)
        text = render_public_messages()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Post Message", callback_data="public:post_help")],
            [InlineKeyboardButton("🔁 Refresh", callback_data="menu:public")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
        ])
        await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    elif choice == "messages":
        # list private threads
        threads = list_user_threads(user_id)
        if not threads:
            txt = "✉️ *Your Messages*\n\nNo private conversations yet."
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
            ])
            await q.edit_message_text(txt, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        else:
            rows = []
            txt_lines = ["✉️ *Your Messages*\n"]
            for tid, th, _last in threads:
                other_id = th["seller_id"] if user_id == th["buyer_id"] else th["buyer_id"]
                product_name = th["product"].get("name") or "Item"
                txt_lines.append(f"• {product_name} (with `{other_id}`)")
                rows.append([InlineKeyboardButton(product_name, callback_data=f"msg:open:{tid}")])
            rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])
            await q.edit_message_text("\n".join(txt_lines), reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.MARKDOWN)

    elif choice == "functions":
        txt = (
            "📘 *Functions*\n"
            "• 🛍️ Shop – browse items\n"
            "• 🗣 Public Chat – global room\n"
            "• ✉️ Messages – your private buyer/seller chats\n"
            "• 💼 Wallet – fiat + Solana address\n"
            "• 🛠 Sell – register + add listings\n"
            "• 📦 Orders – view purchases\n"
            "• 🇸🇬 PayNow / 💳 Stripe – mock payments\n"
            "• 🔄 Refresh – update UI\n"
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]])
        await q.edit_message_text(txt, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    elif choice == "settings":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]])
        await q.edit_message_text("⚙️ *Settings*\n• Notifications: ON\n• Currency: USD",
                                  reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    elif choice == "help":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]])
        await q.edit_message_text("💬 *Help*\nDM: @yourusername\nUse /start anytime.",
                                  reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    elif choice == "refresh" or choice == "main":
        _ = get_user_wallet(user_id)
        kb, text = build_main_menu(get_balance(user_id))
        await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

# ==========================
# SHOP → BUY → CHECKOUT
# ==========================
async def on_buy(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, qty: int):
    q = update.callback_query
    await q.answer()
    item = get_any_product_by_sku(sku)
    if not item:
        await q.answer("Item not found.", show_alert=True)
        return
    qty = clamp_qty(qty)
    total = float(item["price"]) * qty
    txt = (
        f"{item.get('emoji','🛒')} *{item['name']}*\n"
        f"Qty: {qty}\n"
        f"Total: *${total:.2f}*\n\nChoose a payment method:"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Pay with Stripe", callback_data=f"stripe:{sku}:{qty}")],
        [InlineKeyboardButton("🇸🇬 PayNow QR", callback_data=f"paynow:{sku}:{qty}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_shop")]
    ])
    await q.edit_message_text(txt, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

async def on_qty(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, qty: int):
    q = update.callback_query
    await q.answer()
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("−", callback_data=f"qty:{sku}:{qty-1}"),
            InlineKeyboardButton(f"Qty: {clamp_qty(qty)}", callback_data="noop"),
            InlineKeyboardButton("+", callback_data=f"qty:{sku}:{qty+1}")
        ],
        [InlineKeyboardButton("✅ Checkout", callback_data=f"checkout:{sku}:{qty}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_shop")]
    ])
    item = get_any_product_by_sku(sku)
    if not item:
        await q.answer("Item not found.", show_alert=True)
        return
    total = float(item["price"]) * clamp_qty(qty)
    txt = (
        f"{item.get('emoji','🛒')} *{item['name']}*\n"
        f"Price: ${item['price']:.2f} | Qty: {clamp_qty(qty)}\n"
        f"Total: *${total:.2f}*\n\nAdjust quantity or checkout:"
    )
    await q.edit_message_text(txt, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

async def on_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, qty: int):
    q = update.callback_query
    await q.answer()
    await on_buy(update, context, sku, qty)

async def create_stripe_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, qty: int):
    q = update.callback_query
    await q.answer()
    user_id = update.effective_user.id
    item = get_any_product_by_sku(sku)
    if not item:
        await q.answer("Item not found.", show_alert=True)
        return
    qty = clamp_qty(qty)
    total = int(float(item["price"]) * 100)

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": item["name"]},
                    "unit_amount": total,
                },
                "quantity": qty,
            }],
            mode="payment",
            success_url="https://example.com/success",
            cancel_url="https://example.com/cancel",
        )
    except Exception as e:
        await q.edit_message_text(f"❌ Stripe error: {e}")
        return

    add_order(user_id, item["name"], qty, float(item["price"]) * qty, "Stripe", int(item.get("seller_id", 0)))

    await q.edit_message_text(
        f"💳 Proceed to payment:\n{session.url}\n\n"
        "After payment, we’ll mark your order as paid (via webhook/manual).",
        parse_mode=ParseMode.MARKDOWN
    )

async def show_paynow(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, qty: int):
    q = update.callback_query
    await q.answer()
    user_id = update.effective_user.id
    item = get_any_product_by_sku(sku)
    if not item:
        await q.answer("Item not found.", show_alert=True)
        return
    qty = clamp_qty(qty)
    total = float(item["price"]) * qty
    qr = generate_paynow_qr(total)
    add_order(user_id, item["name"], qty, total, "PayNow", int(item.get("seller_id", 0)))

    await q.message.reply_photo(
        photo=InputFile(qr, filename="paynow.png"),
        caption=f"🇸🇬 PayNow *${total:.2f}*\nSend proof after payment.\n\nUse /start to return to menu.",
        parse_mode=ParseMode.MARKDOWN
    )

# ==========================
# CONTACT SELLER → PRIVATE CHAT
# ==========================
async def on_contact_seller(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, seller_id: int):
    q = update.callback_query
    await q.answer()
    buyer_id = update.effective_user.id

    product = get_any_product_by_sku(sku)
    if not product:
        await q.answer("Item not found.", show_alert=True)
        return

    thread_id = new_chat_thread(buyer_id, seller_id, product)

    buyer_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Open Chat", callback_data=f"chat:open:{thread_id}")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
    ])
    await q.edit_message_text(
        f"🧑‍💻 *Contact Seller*\nItem: *{product['name']}*\n\nTap *Open Chat* to start a private chat.",
        reply_markup=buyer_kb, parse_mode=ParseMode.MARKDOWN
    )

    if seller_id and seller_id != 0:
        try:
            await context.bot.send_message(
                seller_id,
                f"📩 New buyer wants to chat about *{product['name']}*.\nTap below to join:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💬 Open Chat", callback_data=f"chat:open:{thread_id}")]
                ]),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.info(f"Could not DM seller {seller_id}: {e}")

async def on_chat_open(update: Update, context: ContextTypes.DEFAULT_TYPE, thread_id: str):
    q = update.callback_query
    await q.answer()
    user_id = update.effective_user.id
    thr = get_thread(thread_id)
    if not thr:
        await q.edit_message_text("❌ Chat no longer exists. Start again with 'Contact Seller'.")
        return
    # turn OFF public mode when going private
    active_public_chat.pop(user_id, None)
    active_chats[user_id] = thread_id
    product_name = thr["product"]["name"]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚪 Exit Chat", callback_data="chat:exit")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
    ])
    await q.edit_message_text(
        f"💬 *Chat Opened*\nTopic: *{product_name}*\n"
        f"Type messages normally and I’ll relay them.\n"
        f"To stop, tap *Exit Chat*.",
        reply_markup=kb, parse_mode=ParseMode.MARKDOWN
    )

# ==========================
# SELLER CENTER FLOWS
# ==========================
async def seller_center_router(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    q = update.callback_query
    user_id = update.effective_user.id

    if action == "register":
        set_role(user_id, "seller")
        text, kb = build_seller_menu("seller")
        await q.edit_message_text("✅ You are now a *Seller*.\n", parse_mode=ParseMode.MARKDOWN)
        await q.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    elif action == "add":
        user_flow_state[user_id] = {"phase": "add_title"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Cancel", callback_data="sell:cancel")]])
        await q.edit_message_text("📝 *Add Listing*\nSend the *Title* of your item:", reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    elif action == "list":
        items = list_seller_products(user_id)
        if not items:
            out = "📄 *My Listings*\n\nYou have no listings."
        else:
            lines = [f"• {p['name']} — ${p['price']:.2f} (SKU: `{p['sku']}`)" for p in items]
            out = "📄 *My Listings*\n\n" + "\n".join(lines)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]])
        await q.edit_message_text(out, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    elif action == "cancel":
        user_flow_state.pop(user_id, None)
        text, kb = build_seller_menu(get_role(user_id))
        await q.edit_message_text("❌ Add listing canceled.", reply_markup=kb)

# ==========================
# MESSAGE HANDLER (TEXT)
# ==========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message
    text = (msg.text or "").strip()
    uid = user.id

    # 1) If user is in PRIVATE chat thread → relay to other side
    if uid in active_chats:
        thread_id = active_chats[uid]
        thr = get_thread(thread_id)
        if thr:
            append_chat_message(thread_id, uid, text)
            to_id = thr["seller_id"] if uid == thr["buyer_id"] else thr["buyer_id"]
            header = f"💬 New message in thread *{thread_id}*\nItem: *{thr['product']['name']}*\n\n"
            try:
                await context.bot.send_message(
                    to_id, header + text,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💬 Open Chat", callback_data=f"chat:open:{thread_id}")],
                        [InlineKeyboardButton("🚪 Exit Chat", callback_data="chat:exit")]
                    ]),
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.info(f"Relay failed to {to_id}: {e}")
            return

    # 2) If user is in PUBLIC chat mode → broadcast to feed
    if active_public_chat.get(uid):
        uname = user.username or user.full_name or f"user_{uid}"
        add_public_message(uid, uname, text)
        # show refreshed public feed
        out = render_public_messages()
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Post Message", callback_data="public:post_help")],
            [InlineKeyboardButton("🔁 Refresh", callback_data="menu:public")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
        ])
        await msg.reply_text(out, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        return

    # 3) Seller add listing flow
    st = user_flow_state.get(uid)
    if st and st.get("phase") == "add_title":
        st["title"] = text
        st["phase"] = "add_price"
        await msg.reply_text("💲 Send the *Price* (e.g., 19.99):", parse_mode=ParseMode.MARKDOWN)
        return

    if st and st.get("phase") == "add_price":
        try:
            price = float(text)
            st["price"] = price
            st["phase"] = "add_desc"
            await msg.reply_text("📝 Send a short *Description*:", parse_mode=ParseMode.MARKDOWN)
        except ValueError:
            await msg.reply_text("❌ Invalid price. Please send a number (e.g., 19.99).")
        return

    if st and st.get("phase") == "add_desc":
        desc = text
        title = st["title"]
        price = st["price"]
        sku = add_seller_product(uid, title, price, desc)
        user_flow_state.pop(uid, None)
        await msg.reply_text(
            f"✅ *Listing Added!*\nTitle: *{title}*\nPrice: ${price:.2f}\nSKU: `{sku}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # 4) Otherwise, nudge to /start
    if text.lower() not in ("/start", "/shop"):
        await msg.reply_text("Type /start to open the menu.")

# ==========================
# CALLBACK ROUTER
# ==========================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""

    try:
        if data.startswith("menu:"):
            await on_menu(update, context)

        elif data.startswith("buy:"):
            _, sku, qty = data.split(":")
            await on_buy(update, context, sku, int(qty))

        elif data.startswith("qty:"):
            _, sku, qty = data.split(":")
            await on_qty(update, context, sku, int(qty))

        elif data.startswith("checkout:"):
            _, sku, qty = data.split(":")
            await on_checkout(update, context, sku, int(qty))

        elif data.startswith("stripe:"):
            _, sku, qty = data.split(":")
            await create_stripe_checkout(update, context, sku, int(qty))

        elif data.startswith("paynow:"):
            _, sku, qty = data.split(":")
            await show_paynow(update, context, sku, int(qty))

        elif data == "back_to_shop":
            text, kb = build_shop_keyboard()
            await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

        elif data.startswith("contact:"):
            _, sku, seller_id = data.split(":")
            await on_contact_seller(update, context, sku, int(seller_id))

        elif data.startswith("chat:open:"):
            _, _, thread_id = data.split(":")
            await on_chat_open(update, context, thread_id)

        elif data == "chat:exit":
            uid = update.effective_user.id
            active_chats.pop(uid, None)
            await q.edit_message_text("🚪 Chat closed. Type /start to return to menu.")

        elif data.startswith("sell:"):
            _, action = data.split(":")
            await seller_center_router(update, context, action)

        # open private message thread from messages list
        elif data.startswith("msg:open:"):
            _, _, thread_id = data.split(":")
            await on_chat_open(update, context, thread_id)

        # wallet actions
        elif data == "wallet:show_sol":
            uid = update.effective_user.id
            sol_wallet = get_user_wallet(uid)
            pub = sol_wallet["public_key"]
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")],
                [InlineKeyboardButton("🔁 Back to Wallet", callback_data="menu:wallet")]
            ])
            await q.edit_message_text(
                f"📥 *Your Solana Deposit Address*\n`{pub}`\n\nSend SOL/USDC-SPL here.",
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN
            )

        elif data == "wallet:send_sol":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")],
                [InlineKeyboardButton("🔁 Back to Wallet", callback_data="menu:wallet")]
            ])
            await q.edit_message_text(
                "📤 *Send SOL*\nThis is a placeholder. Add a multi-step flow to ask for address + amount, then call send_sol(...).",
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN
            )

        # public chat helper button
        elif data == "public:post_help":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔁 Refresh", callback_data="menu:public")],
                [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
            ])
            await q.edit_message_text(
                "🗣 *Public Chat*\nJust send a normal text message and it will appear here for everyone.",
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN
            )

        elif data == "noop":
            pass

    except Exception as e:
        logger.exception("Callback error")
        try:
            await q.edit_message_text(f"⚠️ Error: {e}\nPlease /start again.")
        except Exception:
            pass

# ==========================
# MAIN
# ==========================
def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN missing in .env")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("shop", shop_cmd))

    # Callback buttons
    app.add_handler(CallbackQueryHandler(callback_router))

    # Text messages (chat relay + seller flows + public chat)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Errors
    app.add_error_handler(lambda u, c: logger.error(c.error))

    print("🤖 Marketplace Bot running — Ctrl+C to stop")
    app.run_polling()

if __name__ == "__main__":
    main()
