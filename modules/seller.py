from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram import Update
from telegram.ext import ContextTypes

from modules import storage

# ==========================
# SELLER MENU
# ==========================

def build_seller_menu(role: str):
    if role != "seller":
        text = (
            "🛠 *Seller Center*\n\n"
            "You’re currently a *buyer*.\n"
            "Register as a seller to list items."
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
# SELLER LISTINGS
# ==========================

async def show_seller_listings(update, context):
    q = update.callback_query
    user_id = update.effective_user.id

    items = storage.list_seller_products(user_id)

    if not items:
        return await q.edit_message_text(
            "📄 *My Listings*\n\nYou have no active listings.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
            ])
        )

    rows = []
    for p in items:
        rows.append([
            InlineKeyboardButton(
                f"{p['name']} — ${p['price']:.2f}",
                callback_data="noop"
            ),
            InlineKeyboardButton(
                "🗑 Remove",
                callback_data=f"sell:remove_confirm:{p['sku']}"
            )
        ])

    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])

    await q.edit_message_text(
        "📄 *My Listings*\n\nSelect a listing to remove:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(rows)
    )


# ==========================
# REMOVE LISTING
# ==========================

async def confirm_remove_listing(update, context, sku: str):
    q = update.callback_query

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes, remove", callback_data=f"sell:remove_do:{sku}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="menu:sell")]
    ])

    await q.edit_message_text(
        f"⚠️ Are you sure you want to delete listing `{sku}`?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )


async def do_remove_listing(update, context, sku: str):
    q = update.callback_query
    user_id = update.effective_user.id

    ok = storage.remove_seller_product(user_id, sku)

    msg = "✅ Listing removed." if ok else "❌ Listing not found."

    await q.edit_message_text(
        msg,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
        ])
    )


# ==========================
# ADD LISTING FLOW
# ==========================

async def start_add_listing(update, context):
    q = update.callback_query
    user_id = update.effective_user.id

    storage.user_flow_state[user_id] = {"phase": "add_title"}

    await q.edit_message_text(
        "📝 *Add Listing*\n\nSend the *product name*:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="sell:cancel")]
        ])
    )


def is_in_seller_flow(user_id: int) -> bool:
    st = storage.user_flow_state.get(user_id)
    return bool(st and st.get("phase", "").startswith("add_"))


async def handle_seller_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    msg = update.effective_message
    user_id = update.effective_user.id
    st = storage.user_flow_state.get(user_id)

    if not st:
        return

    # STEP 1 — TITLE
    if st["phase"] == "add_title":
        st["title"] = text
        st["phase"] = "add_price"
        return await msg.reply_text(
            "💲 Send the *price* (e.g. 19.99):",
            parse_mode=ParseMode.MARKDOWN
        )

    # STEP 2 — PRICE
    if st["phase"] == "add_price":
        try:
            price = float(text)
            if price <= 0:
                raise ValueError
        except ValueError:
            return await msg.reply_text("❌ Invalid price. Please send a number.")

        st["price"] = price
        st["phase"] = "add_desc"
        return await msg.reply_text(
            "📝 Send a short *description*:",
            parse_mode=ParseMode.MARKDOWN
        )

    # STEP 3 — DESCRIPTION (FINAL)
    if st["phase"] == "add_desc":
        title = st["title"]
        price = st["price"]
        desc = text

        sku = storage.add_seller_product(user_id, title, price, desc)
        storage.user_flow_state.pop(user_id, None)

        await msg.reply_text(
            f"✅ *Listing Added!*\n\n"
            f"• *Title:* {title}\n"
            f"• *Price:* ${price:.2f}\n"
            f"• *SKU:* `{sku}`",
            parse_mode=ParseMode.MARKDOWN
        )


# ==========================
# SELLER REGISTRATION
# ==========================

async def register_seller(update, context):
    q = update.callback_query
    user_id = update.effective_user.id

    storage.set_role(user_id, "seller")
    text, kb = build_seller_menu("seller")

    await q.edit_message_text(
        "✅ You are now registered as a *Seller*!",
        parse_mode=ParseMode.MARKDOWN
    )
    await q.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
