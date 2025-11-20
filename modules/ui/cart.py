from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from modules import db


async def build_cart_view(user_id):
    items = await db.cart_get(user_id)

    if not items:
        return (
            "🛒 *Your cart is empty*",
            InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]])
        )

    lines = [
        f"• *{i['title']}* × {i['quantity']} — ${float(i['price']) * i['quantity']:.2f}"
        for i in items
    ]

    total = sum(float(i["price"]) * i["quantity"] for i in items)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Checkout", callback_data="v2:checkout_cart")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]
    ])

    return (
        "🛒 *Your Cart*\n\n" + "\n".join(lines) + f"\n\nTotal: *${total:.2f}*",
        kb
    )
