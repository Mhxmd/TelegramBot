from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram import Update
from telegram.ext import ContextTypes

from modules import storage


def remove_seller_product(seller_id: int, sku: str):
    """Deletes a product listing by SKU."""
    data = storage.load_json(storage.SELLER_PRODUCTS_FILE)
    items = data.get(str(seller_id), [])
    new_items = [p for p in items if p["sku"] != sku]
    data[str(seller_id)] = new_items
    storage.save_json(storage.SELLER_PRODUCTS_FILE, data)
    return len(items) != len(new_items)  # returns True if something was deleted

async def show_seller_listings(update, context):
    """Shows seller’s listings with remove buttons."""
    q = update.callback_query
    user_id = update.effective_user.id
    items = storage.load_json(storage.SELLER_PRODUCTS_FILE).get(str(user_id), [])
    if not items:
        await q.edit_message_text(
            "📄 *My Listings*\n\nYou have no active listings.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]])
        )
        return
    rows = []
    for p in items:
        rows.append([
            InlineKeyboardButton(f"{p['name']} - ${p['price']:.2f}", callback_data="noop"),
            InlineKeyboardButton("🗑 Remove", callback_data=f"sell:remove_confirm:{p['sku']}")
        ])
    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])
    await q.edit_message_text("📄 *My Listings*\n\nSelect one to remove:", parse_mode=ParseMode.MARKDOWN,
                              reply_markup=InlineKeyboardMarkup(rows))

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
    ok = remove_seller_product(user_id, sku)
    msg = "✅ Listing removed." if ok else "❌ Could not find that listing."
    await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]]))


def build_seller_menu(role: str):
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


async def seller_center_router(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    q = update.callback_query
    user_id = update.effective_user.id

    if action == "register":
        storage.set_role(user_id, "seller")
        text, kb = build_seller_menu("seller")
        await q.edit_message_text("✅ You are now a *Seller*.\n", parse_mode=ParseMode.MARKDOWN)
        await q.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    elif action == "add":
        storage.user_flow_state[user_id] = {"phase": "add_title"}
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Cancel", callback_data="sell:cancel")]])
        await q.edit_message_text("📝 *Add Listing*\nSend the *Title* of your item:", reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    elif action == "list":
        items = storage.list_seller_products(user_id)
        if not items:
            out = "📄 *My Listings*\n\nYou have no listings."
        else:
            lines = [f"• {p['name']} — ${p['price']:.2f} (SKU: `{p['sku']}`)" for p in items]
            out = "📄 *My Listings*\n\n" + "\n".join(lines)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]])
        await q.edit_message_text(out, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

    elif action == "cancel":
        storage.user_flow_state.pop(user_id, None)
        text, kb = build_seller_menu(storage.get_role(user_id))
        await q.edit_message_text("❌ Add listing canceled.", reply_markup=kb)


def is_in_seller_flow(user_id: int) -> bool:
    st = storage.user_flow_state.get(user_id)
    return bool(st and st.get("phase", "").startswith("add_"))


async def handle_seller_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    msg = update.effective_message
    user_id = update.effective_user.id
    st = storage.user_flow_state.get(user_id)
    if not st:
        return

    if st.get("phase") == "add_title":
        st["title"] = text
        st["phase"] = "add_price"
        await msg.reply_text("💲 Send the *Price* (e.g., 19.99):", parse_mode=ParseMode.MARKDOWN)
        return

    if st.get("phase") == "add_price":
        try:
            price = float(text)
        except ValueError:
            await msg.reply_text("❌ Invalid price. Please send a number (e.g., 19.99).")
            return
        st["price"] = price
        st["phase"] = "add_desc"
        await msg.reply_text("📝 Send a short *Description*:", parse_mode=ParseMode.MARKDOWN)
        return

    if st.get("phase") == "add_desc":
        desc = text
        title = st["title"]
        price = st["price"]
        sku = storage.add_seller_product(user_id, title, price, desc)
        storage.user_flow_state.pop(user_id, None)
        await msg.reply_text(
            f"✅ *Listing Added!*\nTitle: *{title}*\nPrice: ${price:.2f}\nSKU: `{sku}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
