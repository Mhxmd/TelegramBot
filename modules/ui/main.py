# modules/ui/main.py

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from modules import db

async def build_main_menu(user_id: int):
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
