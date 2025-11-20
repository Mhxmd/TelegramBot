from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_category_menu(categories):
    rows = [
        [InlineKeyboardButton(cat, callback_data=f"v2:shop:cat:{cat}")]
        for cat in categories
    ]

    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")])

    text = "🛍 *Shop Categories*\n\nChoose a category:"
    return text, InlineKeyboardMarkup(rows)
