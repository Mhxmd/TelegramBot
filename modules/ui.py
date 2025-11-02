import stripe
import qrcode
from io import BytesIO
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.constants import ParseMode
from telegram import Update
from telegram.ext import ContextTypes

# Import core modules (no circular imports)
from modules import storage, seller, chat
import modules.wallet_utils as wallet


# built-in catalog
CATALOG = {
    "cat": {"name": "Cat", "price": 15, "emoji": "🐱", "seller_id": 0, "desc": "Cute cat plush."},
    "hoodie": {"name": "Hoodie", "price": 30, "emoji": "🧥", "seller_id": 0, "desc": "Comfy cotton hoodie."},
    "blackcap": {"name": "Black Cap", "price": 12, "emoji": "🧢", "seller_id": 0, "desc": "Minimalist black cap."},
}


def clamp_qty(qty: int) -> int:
    return max(1, min(int(qty), 99))


def enumerate_all_products():
    items = []
    # built-in
    for sku, p in CATALOG.items():
        items.append({**p, "sku": sku})
    # sellers
    data = storage.load_json(storage.SELLER_PRODUCTS_FILE)
    for sid, plist in data.items():
        for it in plist:
            items.append(it)
    return items


def build_main_menu(balance: float):
    buttons = [
        [InlineKeyboardButton("🛍️ Shop", callback_data="menu:shop"),
         InlineKeyboardButton("📦 Orders", callback_data="menu:orders")],
        [InlineKeyboardButton("💼 Wallet", callback_data="menu:wallet"),
         InlineKeyboardButton("🛠 Sell", callback_data="menu:sell")],
        [InlineKeyboardButton("💬 Public Chat", callback_data="chat:public_open"),
         InlineKeyboardButton("✉️ Messages", callback_data="menu:messages")],
        [InlineKeyboardButton("⚙️ Functions", callback_data="menu:functions"),
         InlineKeyboardButton("🔄 Refresh", callback_data="menu:refresh")],
    ]
    text = (
        "👋 *Welcome to Telegram Marketplace!*\n\n"
        f"💰 Balance: *${balance:.2f}*\n—\n"
        "Browse, sell, chat, or manage your wallet."
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


async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    _, choice = (q.data or "menu:").split(":", 1)
    user_id = update.effective_user.id

    if choice == "shop":
        text, kb = build_shop_keyboard()
        await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    elif choice == "orders":
        orders = storage.list_orders(user_id)
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
        # Local import to avoid circular import error
        import modules.wallet_utils as wallet

        bal = storage.get_balance(user_id)
        user_w = wallet.ensure_user_wallet(user_id)
        pub = user_w["public_key"]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Deposit SOL", callback_data="wallet:deposit")],
            [InlineKeyboardButton("📤 Withdraw SOL", callback_data="wallet:withdraw")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")],
        ])
        await q.edit_message_text(
            f"💼 *Wallet*\n\nFiat: *${bal:.2f}*\nOn-chain (Solana): `{pub}`\n\nUse the options below:",
            reply_markup=kb,
            parse_mode=ParseMode.MARKDOWN
        )

    elif choice == "sell":
        role = storage.get_role(user_id)
        text, kb = seller.build_seller_menu(role)
        await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    elif choice == "messages":
        threads = storage.load_json(storage.MESSAGES_FILE)
        buttons = []
        for tid, th in threads.items():
            if th.get("buyer_id") == user_id or th.get("seller_id") == user_id:
                product_name = th["product"]["name"]
                buttons.append([InlineKeyboardButton(f"💬 {product_name}", callback_data=f"chat:open:{tid}")])
        if not buttons:
            buttons = [[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]]
            await q.edit_message_text("💌 *Messages*\n\nYou don’t have any active chats.", reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)
        else:
            buttons.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])
            await q.edit_message_text("💌 *Your Chats*\nSelect a thread:", reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)

    elif choice == "functions":
        await show_functions_menu(update, context)

    elif choice == "help":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]])
        await q.edit_message_text("💬 *Help*\nDM: @yourusername\nUse /start anytime.",
                                  reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    elif choice == "refresh" or choice == "main":
        bal = storage.get_balance(user_id)
        kb, text = build_main_menu(bal)
        await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


async def show_functions_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍️ Shop", callback_data="menu:shop")],
        [InlineKeyboardButton("💌 Messages", callback_data="menu:messages")],
        [InlineKeyboardButton("💬 Public Chat", callback_data="chat:public_open")],
        [InlineKeyboardButton("🛠 Seller Tools", callback_data="menu:sell")],
        [InlineKeyboardButton("🏠 Back", callback_data="menu:main")],
    ])
    await q.edit_message_text("⚙️ *Functions*\nChoose an option:", reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


def generate_paynow_qr(amount: float, name="TestBotShop") -> BytesIO:
    data = f"PayNow to {name} - Amount: ${amount:.2f}"
    img = qrcode.make(data)
    bio = BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return bio
