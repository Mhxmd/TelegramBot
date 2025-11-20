from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_payment_method_menu(order_id, amount):
    text = (
        f"💰 *Checkout*\n\n"
        f"Order ID: `{order_id}`\n"
        f"Amount: *${amount:.2f}*\n\n"
        "Choose payment method:"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 PayNow", callback_data=f"v2:pay:paynow:{order_id}")],
        [InlineKeyboardButton("💳 Stripe", callback_data=f"v2:pay:stripe:{order_id}")],
        [InlineKeyboardButton("⚡ Solana", callback_data=f"v2:pay:solana:{order_id}")],
        [InlineKeyboardButton("🔙 Menu", callback_data="v2:menu:main")]
    ])

    return text, kb


def build_paynow_qr(order_id, amount):
    text = (
        f"📱 *PayNow Payment*\n\n"
        f"Order: `{order_id}`\n"
        f"Amount: *${amount:.2f}*\n\n"
        "_This is a placeholder QR. Real PayNow requires an SGQR issuer._"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I HAVE PAID", callback_data=f"v2:pay:confirm:{order_id}")],
        [InlineKeyboardButton("🔙 Menu", callback_data="v2:menu:main")]
    ])

    return text, kb
