from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_orders_list(orders, for_role, page, total_pages):
    if not orders:
        return (
            "📦 No orders found.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]])
        )

    lines = [
        f"• *Order #{o['order_id']}*\n"
        f"Status: `{o['order_status']}`\n"
        f"Total: *${float(o['total_amount']):.2f}*\n"
        for o in orders
    ]

    text = "📬 *Your Orders*\n\n" + "\n".join(lines) + f"\nPage {page}/{total_pages}"

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ Prev", callback_data=f"v2:buyer:orders_page:{page - 1}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"v2:buyer:orders_page:{page + 1}")
        ],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]
    ])

    return text, kb


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
