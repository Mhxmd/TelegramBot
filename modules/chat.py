import time, asyncio, random
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode, ChatAction
from telegram.ext import ContextTypes
from modules import storage

# State tracking
rate_limit = {}
recent_seen = {}
typing_indicators = {}

# ----------------- Helpers -----------------
def is_in_private_thread(user_id: int) -> bool:
    return user_id in storage.active_private_chats

def is_in_public_chat(user_id: int) -> bool:
    return user_id in storage.active_public_chat

async def send_typing_action(context, chat_id, text=None):
    """Simulates human-like typing before sending."""
    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    delay = min(3.5, max(0.6, len(text or "") / 25)) + random.uniform(-0.25, 0.35)
    await asyncio.sleep(delay)

async def smart_send(context, chat_id, text, reply_markup=None):
    """Sends a message with simulated typing."""
    await send_typing_action(context, chat_id, text)
    try:
        return await context.bot.send_message(
            chat_id, text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup
        )
    except Exception:
        return None

def format_msg(author, text, ts=None):
    ts = ts or time.time()
    stamp = datetime.fromtimestamp(ts).strftime("%H:%M")
    return f"💭 *{author}* @ {stamp}\n{text}"

# ----------------- Typing Indicator -----------------
async def show_typing_indicator(context, chat_id, user_name):
    """Displays '_user is typing..._' and deletes it after 2 seconds."""
    if chat_id in typing_indicators:
        return
    try:
        msg = await context.bot.send_message(
            chat_id, f"💬 _{user_name} is typing..._", parse_mode=ParseMode.MARKDOWN
        )
        typing_indicators[chat_id] = msg.message_id
        await asyncio.sleep(2.5)
        await context.bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
    except Exception:
        pass
    finally:
        typing_indicators.pop(chat_id, None)

# ----------------- Private Chat Flow -----------------
async def on_contact_seller(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str, seller_id: int):
    q = update.callback_query
    buyer = update.effective_user
    buyer_id = buyer.id

    from modules.ui import get_any_product_by_sku
    product = get_any_product_by_sku(sku)
    if not product:
        await q.answer("Item not found.", show_alert=True)
        return

    thread_id = storage.create_thread(buyer_id, seller_id, product)
    storage.active_private_chats[buyer_id] = thread_id

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Open Chat", callback_data=f"chat:open:{thread_id}")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
    ])

    await q.edit_message_text(
        f"🧑‍💻 *Contact Seller*\nItem: *{product['name']}*\n\nTap *Open Chat* to start messaging.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

    # Notify seller or queue reminder if offline
    try:
        await smart_send(
            context, seller_id,
            f"📩 *New Buyer Alert!*\n{buyer.first_name} wants to chat about *{product['name']}!*"
        )
    except Exception:
        # Seller hasn't started bot yet
        storage.add_pending_notification(
            seller_id,
            f"🕓 *Missed Message*\n{buyer.first_name} wanted to chat about *{product['name']}*.\n"
            f"You can reply once you open the bot."
        )
        await q.message.reply_text(
            "🕓 The seller hasn’t opened the bot yet.\n"
            "I’ll deliver your message automatically once they come online."
        )

async def on_chat_open(update: Update, context: ContextTypes.DEFAULT_TYPE, thread_id: str):
    q = update.callback_query
    uid = update.effective_user.id
    thr = storage.get_thread(thread_id)
    if not thr:
        await q.edit_message_text("❌ Chat no longer exists. Start again with 'Contact Seller'.")
        return

    storage.active_private_chats[uid] = thread_id
    product = thr["product"]
    msgs = thr.get("messages", [])[-5:]

    preview = "\n".join(
        format_msg("You" if m["from"] == uid else "Other", m["text"], m["ts"])
        for m in msgs
    ) if msgs else "_No previous messages._"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚪 Exit Chat", callback_data="chat:exit")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
    ])

    await q.edit_message_text(
        f"💬 *Chat Opened*\nTopic: *{product['name']}*\n─────────────────────\n"
        f"{preview}\n─────────────────────\nType your message below:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

async def handle_private_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    uid = update.effective_user.id
    msg = update.effective_message
    thread_id = storage.active_private_chats.get(uid)
    thr = storage.get_thread(thread_id)

    if not thr:
        storage.active_private_chats.pop(uid, None)
        await msg.reply_text("❌ Chat not found. Open again from Messages.")
        return

    # Rate limit
    if uid in rate_limit and time.time() - rate_limit[uid] < 1:
        return
    rate_limit[uid] = time.time()

    storage.append_chat_message(thread_id, uid, text)
    other_id = thr["seller_id"] if uid == thr["buyer_id"] else thr["buyer_id"]
    user_name = update.effective_user.first_name or f"User {uid}"

    # Show typing indicator to other user
    asyncio.create_task(show_typing_indicator(context, other_id, user_name))

    try:
        await send_typing_action(context, other_id, text)
        await context.bot.send_message(
            other_id,
            format_msg(user_name, text),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 Reply", callback_data=f"chat:open:{thread_id}")],
                [InlineKeyboardButton("🚪 Exit Chat", callback_data="chat:exit")]
            ])
        )

        # Delivery animation
        await asyncio.sleep(1.2)
        await msg.reply_text("✅ Delivered", quote=False)
        await asyncio.sleep(1.5)
        await msg.edit_text("👀 Seen", parse_mode=None)

    except Exception:
        # If receiver hasn't started the bot
        storage.add_pending_notification(
            other_id,
            f"📨 *Offline Message*\n{user_name} sent:\n> {text}"
        )
        await msg.reply_text(
            "🕓 The user is offline. I’ll deliver your message once they come online.",
            quote=False
        )

async def on_chat_exit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    storage.active_private_chats.pop(uid, None)
    if uid in storage.active_public_chat:
        storage.active_public_chat.remove(uid)
        for other_id in list(storage.active_public_chat):
            try:
                await context.bot.send_message(
                    other_id,
                    f"👋 A user has left the public chat.",
                    parse_mode=ParseMode.MARKDOWN
                )
            except:
                pass
    await q.edit_message_text("🚪 Chat closed. Type /start to return to menu.")

# ----------------- Public Chat -----------------
async def on_public_chat_open(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    name = update.effective_user.first_name or f"User {uid}"

    if uid not in storage.active_public_chat:
        storage.active_public_chat.add(uid)
        for other_id in list(storage.active_public_chat):
            if other_id != uid:
                try:
                    await context.bot.send_message(
                        other_id, f"🔔 *{name}* joined the chat!",
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception:
                    pass

    storage.active_private_chats.pop(uid, None)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚪 Exit Chat", callback_data="chat:exit")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
    ])
    await q.edit_message_text(
        "🌐 *Public Chat Room*\nChat with anyone using this bot. Be respectful.\nType your message below:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

async def handle_public_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    uid = update.effective_user.id
    msg = update.effective_message
    user_name = update.effective_user.first_name or f"User {uid}"

    # Rate limit
    if uid in rate_limit and time.time() - rate_limit[uid] < 1.5:
        return
    rate_limit[uid] = time.time()

    for other_id in list(storage.active_public_chat):
        if other_id == uid:
            continue
        asyncio.create_task(show_typing_indicator(context, other_id, user_name))
        try:
            await send_typing_action(context, other_id, text)
            await context.bot.send_message(
                other_id,
                f"💭 *{user_name}*: {text}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🚪 Exit Chat", callback_data="chat:exit")]
                ])
            )
        except Exception:
            pass
