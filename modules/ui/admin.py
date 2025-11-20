from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_admin_panel_menu():
    text = "🛠 *Admin Panel*\nChoose an option:"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 View Stats", callback_data="v2:admin:stats")],
        [InlineKeyboardButton("🛍 Products", callback_data="v2:admin:products")],
        [InlineKeyboardButton("👥 Users", callback_data="v2:admin:users")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]
    ])

    return text, kb
