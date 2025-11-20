from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_wallet_dashboard(wallet_row, user_row):
    balance = float(wallet_row["balance"])
    sol = wallet_row["solana_address"]

    text = (
        "💼 *Wallet*\n\n"
        f"Balance: *${balance:.2f}*\n"
        f"Solana Address:\n`{sol}`\n\n"
        f"Role: `{user_row['role']}`"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="v2:wallet:refresh")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")]
    ])

    return text, kb
