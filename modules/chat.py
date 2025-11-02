import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram import Update
from telegram.ext import ContextTypes

from modules import storage

# simple cache for typing indicator later
# active_private_chats is already in storage
# active_public_chat is already in storage


# ------------- helpers -------------
def is_in_private_thread(user_id: int) -> bool:
    return user_id in storage.active_private_chats


def is_in_public_chat(user_id: int) -> bool:
    return user_id in storage.active_public_chat


# ------------- private chat flow -------------
async def on_contact_seller(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, seller_id: int):
    q = update.callback_query
    buyer_id = update.effective_user.id

    # get product from ui-like lookup
    from modules.ui import get_any_product_by_sku
    product = get_any_product_by_sku(sku)
    if not product:
        await q.answer("Item not found.", show_alert=True)
        return

    thread_id = storage.create_thread(buyer_id, seller_id, product)

    # mark buyer in this thread
    storage.active_private_chats[buyer_id] = thread_id

    buyer_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Open Chat", callback_data=f"chat:open:{thread_id}")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
    ])
    await q.edit_message_text(
        f"🧑‍💻 *Contact Seller*\nItem: *{product['name']}*\n\nTap *Open Chat* to start a private chat.",
        reply_markup=buyer_kb, parse_mode=ParseMode.MARKDOWN
    )

    if seller_id and seller_id != 0:
        try:
            await context.bot.send_message(
                seller_id,
                f"📩 New buyer wants to chat about *{product['name']}*.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💬 Open Chat", callback_data=f"chat:open:{thread_id}")]
                ]),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass


async def on_chat_open(update: Update, context: ContextTypes.DEFAULT_TYPE, thread_id: str):
    q = update.callback_query
    uid = update.effective_user.id
    thr = storage.get_thread(thread_id)
    if not thr:
        await q.edit_message_text("❌ Chat no longer exists. Start again with 'Contact Seller'.")
        return

    # attach user
    storage.active_private_chats[uid] = thread_id
    product_name = thr["product"]["name"]

    # show last 3 messages (if any)
    recent = thr.get("messages", [])[-3:]
    msg_lines = []
    for m in recent:
        author = "You" if m["from"] == uid else "Other"
        ts = time.strftime("%H:%M", time.localtime(m["ts"]))
        msg_lines.append(f"_{author} @ {ts}_: {m['text']}")
    recent_txt = "\n".join(msg_lines) if msg_lines else "_No previous messages._"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚪 Exit Chat", callback_data="chat:exit")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
    ])
    await q.edit_message_text(
        f"💬 *Chat Opened*\nTopic: *{product_name}*\n\n{recent_txt}\n\nType your message:",
        reply_markup=kb, parse_mode=ParseMode.MARKDOWN
    )


async def on_chat_exit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    storage.active_private_chats.pop(uid, None)
    storage.active_public_chat.discard(uid)
    await q.edit_message_text("🚪 Chat closed. Type /start to return to menu.")


async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    uid = update.effective_user.id
    msg = update.effective_message
    thread_id = storage.active_private_chats.get(uid)
    thr = storage.get_thread(thread_id)
    if not thr:
        # clean up
        storage.active_private_chats.pop(uid, None)
        await msg.reply_text("❌ Chat not found. Open again from Messages.")
        return

    # save sender message
    storage.append_chat_message(thread_id, uid, text)

    # find counterpart
    other_id = thr["seller_id"] if uid == thr["buyer_id"] else thr["buyer_id"]
    header = (
        f"💬 *New message*\n"
        f"Item: *{thr['product']['name']}*\n"
        f"From: `{uid}`\n\n"
    )

    # send to counterpart
    try:
        await context.bot.send_message(
            other_id,
            header + text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Open Chat", callback_data=f"chat:open:{thread_id}")],
                [InlineKeyboardButton("🚪 Exit Chat", callback_data="chat:exit")],
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception:
        pass


# ------------- public chat -------------
async def on_public_chat_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id

    # mark user
    storage.active_public_chat.add(uid)
    # remove from private if any
    storage.active_private_chats.pop(uid, None)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚪 Exit Chat", callback_data="chat:exit")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
    ])
    await q.edit_message_text(
        "🌐 *Public Chat Room*\nYou can talk to anyone using this bot.\nType your message below.",
        reply_markup=kb,
        parse_mode=ParseMode.MARKDOWN
    )


async def handle_public_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    uid = update.effective_user.id
    msg = update.effective_message

    # rebroadcast to all in public chat except sender
    for other_id in list(storage.active_public_chat):
        if other_id == uid:
            continue
        try:
            await context.bot.send_message(
                other_id,
                f"🌐 *Public Chat*\n`{uid}`: {text}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚪 Exit Chat", callback_data="chat:exit")]
                ])
            )
        except Exception:
            pass

    # confirm to sender
    await msg.reply_text("✅ Sent to public chat.")
