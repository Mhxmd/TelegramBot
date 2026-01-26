from asyncio.log import logger
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram import Update
from telegram.error import BadRequest 
from telegram.ext import ContextTypes
from telegram.error import BadRequest 
from telegram.ext import ContextTypes
from modules import shopping_cart, storage

import datetime as _dt

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
            [InlineKeyboardButton("📄 My Listings", callback_data="sell:list"),
            InlineKeyboardButton("✏ Update Stock", callback_data="sell:pick_stock")],   # <-- NEW
            [InlineKeyboardButton("📈 Analytics", callback_data="analytics:30")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")]
        ])

    return text, kb

# Seller Application Status Menu

def apply_for_seller(user_id: int):
    storage.set_role(user_id, "seller")
    storage.set_seller_status(user_id, "pending_captcha")

import random

def generate_captcha():
    """
    Simple human-verification captcha.
    Returns: (question: str, answer: str)
    """
    a = random.randint(1, 9)
    b = random.randint(1, 9)
    op = random.choice(["+", "-"])

    if op == "+":
        answer = a + b
    else:
        # avoid negatives
        if b > a:
            a, b = b, a
        answer = a - b

    question = f"What is {a} {op} {b}?"

    return question, str(answer)


#Captca handling function

def verify_captcha(user_id: int, answer: int):
    st = storage.user_flow_state.get(user_id)
    if not st or st.get("phase") != "captcha":
        return False

    if int(answer) == st["answer"]:
        storage.set_seller_status(user_id, "human_verified")
        storage.user_flow_state.pop(user_id, None)
        return True

    return False


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

    rows = []                       # ← initialise list
    for p in items:
        rows.append([
            InlineKeyboardButton(
                f"{p['name']} — ${p['price']:.2f}",
                callback_data="noop"
            ),
            InlineKeyboardButton("✏ Stock", callback_data=f"sell:stock:{p['sku']}"),
            InlineKeyboardButton("🗑 Remove", callback_data=f"sell:remove_confirm:{p['sku']}")
        ])

    rows.append([InlineKeyboardButton("🏠 Menu", callback_data="menu:main")])

    await q.edit_message_text(
        "📄 *My Listings*\n\nTap ✏ to change stock or 🗑 to remove:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(rows)
    )

# ==========================
# Analytics for Seller
# ==========================

async def show_analytics(update, context, days: int = 30):
    q = update.callback_query
    seller_uid = update.effective_user.id

    data = _seller_analytics(seller_uid, days)

    text = (
        f"📈 *Seller Analytics*  –  {data['period']}\n\n"
        f"• *Active listings:* {data['active']}\n"
        f"• *Total orders:* {data['orders']}\n"
        f"• *Completed:* {data['completed']}\n"
        f"• *Conversion:* {data['conv_rate']} %\n"
        f"• *Units sold:* {data['units']}\n"
        f"• *Revenue:* ${data['revenue']:.2f}\n"
        f"• *Top SKU:* `{data['top_sku'] or 'N/A'}`"
    )

    try:
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=_analytics_kb())
    except BadRequest as e:
        if "message is not modified" in str(e).lower():
            await q.answer()          # acknowledge silently
        else:
            raise 
                            # real error, re-raise

# ==========================
# Update Stock
# ==========================

async def pick_product_to_update_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user_id = update.effective_user.id
    items = storage.list_seller_products(user_id)
    if not items:
        return await q.answer("You have no listings to update.", show_alert=True)

    rows = [[InlineKeyboardButton(f"{p['name']} ({p['stock']} left)",
                                  callback_data=f"sell:stock:{p['sku']}")]
            for p in items[:8]]  # cap at 8 for neatness
    rows.append([InlineKeyboardButton("🔙 Seller Center", callback_data="menu:sell")])
    await q.edit_message_text("📦 *Which item do you want to update?*",
                              parse_mode=ParseMode.MARKDOWN,
                              reply_markup=InlineKeyboardMarkup(rows))

async def prompt_update_stock(update: Update, context: ContextTypes.DEFAULT_TYPE, sku: str):
    q = update.callback_query
    user_id = update.effective_user.id
    logger.info(f"[STOCK] uid={user_id} sku={sku}")

    # make sure the seller actually owns this SKU
    _, prod = storage.get_seller_product_by_sku(sku)
    if not prod or int(prod.get("seller_id", 0)) != user_id:
        logger.warning(f"[STOCK] ownership fail prod={prod}")
        return await q.answer("❌ Not your product.", show_alert=True)

    # store state so the next text message is treated as the new quantity
    storage.user_flow_state[user_id] = {"phase": "update_stock", "sku": sku}

    await q.edit_message_text(
        f"📦 Send the *new stock quantity* for `{prod['name']}`:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data="menu:main")
        ]])
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
# Analytical
# ==========================
async def show_single_product_analytics(update, context, sku: str):
    q = update.callback_query
    seller_uid = update.effective_user.id

    # get all completed orders for this sku + seller
    orders = storage.get_seller_orders_since(seller_uid, _dt.date.min)
    completed = [o for o in orders if o.get("status") == "completed" and o.get("sku") == sku]

    revenue = sum(float(o["total"]) for o in completed)
    units   = sum(int(o["qty"]) for o in completed)

    item = shopping_cart.get_any_product_by_sku(sku) or {}

    text = (
        f"📈 *Product Analytics* – `{sku}`\n\n"
        f"📦 *Name:* {item.get('name', sku)}\n"
        f"💰 *Revenue:* ${revenue:.2f}\n"
        f"📦 *Units Sold:* {units}\n"
        f"📊 *Completed Orders:* {len(completed)}"
    )

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Back to Item", callback_data=f"view_item:{sku}"),
        InlineKeyboardButton("🏠 Main Menu", callback_data="menu:main")
    ]])

    await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

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

    # ---------- ADD / EDIT LISTING FLOW ----------
    if st["phase"] == "add_title":
        st["title"] = text
        st["phase"] = "add_price"
        return await msg.reply_text("💲 Send the *price* (e.g. 19.99):", parse_mode=ParseMode.MARKDOWN)

    if st["phase"] == "add_price":
        try:
            price = float(text)
            if price <= 0:
                raise ValueError
        except ValueError:
            return await msg.reply_text("❌ Invalid price. Please send a number.")
        st["price"] = price
        st["phase"] = "add_qty"
        return await msg.reply_text("📦 Send the quantity (stock), e.g. 5:", parse_mode=ParseMode.MARKDOWN)

    if st["phase"] == "add_qty":
        try:
            qty = int(text.strip())
            if qty <= 0:
                raise ValueError
        except Exception:
            return await msg.reply_text("❌ Invalid quantity. Send a whole number above 0.")
        st["qty"] = qty
        st["phase"] = "add_desc"
        return await msg.reply_text("📝 Send a short *description*:", parse_mode=ParseMode.MARKDOWN)

    if st["phase"] == "add_desc":
        st["desc"] = text
        st["phase"] = "add_image"
        return await msg.reply_text("📸 Send a *picture* of the item (or send /skip to use no image):", parse_mode=ParseMode.MARKDOWN)

    # ---------- UPDATE STOCK (standalone) ----------
    if st["phase"] == "update_stock":
        try:
            new_qty = int(text.strip())
            if new_qty < 0:
                raise ValueError
        except ValueError:
            return await msg.reply_text("❌ Send a whole number ≥ 0.")

        sku   = st["sku"]
        title = storage.get_any_product_by_sku(sku).get("name", sku)
        storage.set_seller_stock(sku, new_qty)
        storage.user_flow_state.pop(user_id, None)          # clear state

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Main Menu", callback_data="menu:main")
        ]])
        await msg.reply_text(
            f"✅ *Stock updated*\n\n"
            f"📦 *{title}* now has *{new_qty}* units.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb
        )
        return   # flow finished

    # ---------- ADD IMAGE (final step of listing) ----------
    if st["phase"] == "add_image":
        if update.effective_message.photo:
            st["image_url"] = update.effective_message.photo[-1].file_id
        elif text and text.lower() == "/skip":
            st["image_url"] = None
        else:
            return await msg.reply_text("Please send a photo or type /skip.")

        title, price, qty, desc = st["title"], st["price"], st["qty"], st["desc"]
        image_url = st.get("image_url")

        try:
            sku = storage.add_seller_product(user_id, title, price, desc, stock=qty, image_url=image_url)
        except Exception as exc:
            logger.exception("add_seller_product failed")
            await msg.reply_text(f"❌ Failed to add product: {exc}")
            return

        storage.user_flow_state.pop(user_id, None)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Main Menu", callback_data="menu:main")],
            [InlineKeyboardButton("🛍 Marketplace", callback_data="menu:shop")]
        ])
        await msg.reply_text(
            f"✅ *Listing Added!*\n\n"
            f"• *Title:* {title}\n"
            f"• *Price:* ${price:.2f}\n"
            f"• *Stock:* {qty}\n"
            f"• *SKU:* `{sku}`" + ("\n• *Image attached*" if image_url else ""),
            parse_mode="Markdown",
            reply_markup=kb
        )

# ==========================
# SELLER REGISTRATION
# ==========================

async def register_seller(update, context):
    q = update.callback_query
    user_id = update.effective_user.id

    storage.set_role(user_id, "seller")
    storage.set_seller_status(user_id, "pending")
    storage.set_role(user_id, "seller")
    

    text, kb = build_seller_menu("seller")

    await q.edit_message_text(
        "✅ You are now registered as a *Seller*!",
        parse_mode=ParseMode.MARKDOWN
    )
    await q.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
# --------------------------------------------------
#  Seller Ship Prompt
# --------------------------------------------------
async def seller_ship_prompt(update, context, order_id):
    q = update.callback_query
    uid = update.effective_user.id
    o = storage.get_order_by_id(order_id)
    if int(o.get("seller_id")) != uid:
        return await q.answer("❌ Not your order", show_alert=True)

    # store temp state
    storage.user_flow_state[uid] = {"phase": "await_tracking", "order_id": order_id}
    await q.edit_message_text("📦 Send me the *tracking number* (or type 'none' if not tracked):",
                              parse_mode="Markdown")

# --------------------------------------------------
#  ANALYTICS  (self-contained in seller.py)
# --------------------------------------------------
def _seller_analytics(seller_uid: int, days: int = 30):
    """Return dict with seller stats for last <days> days (days=0 → all-time)."""
    since = _dt.date.min if days == 0 else _dt.date.today() - _dt.timedelta(days=days)
    orders = storage.get_seller_orders_since(seller_uid, since)   # expects list[dict]
    listings = storage.list_seller_products(seller_uid)

    completed = [o for o in orders if o.get("status") == "completed"]
    revenue = sum(float(o["total"]) for o in completed)
    units = sum(int(o["qty"]) for o in completed)

    # best-selling SKU
    sku_sales = {}
    for o in completed:
        sku = o["sku"]
        sku_sales[sku] = sku_sales.get(sku, 0) + int(o["qty"])
    top_sku = max(sku_sales.items(), key=lambda x: x[1])[0] if sku_sales else None

    return {
        "period"   : f"{days} day{'s' if days!=1 else ''}" if days else "All-time",
        "orders"   : len(orders),
        "completed": len(completed),
        "revenue"  : revenue,
        "units"    : units,
        "conv_rate": round(len(completed) / len(orders) * 100, 1) if orders else 0,
        "top_sku"  : top_sku,
        "active"   : len(listings)
    }


def _analytics_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 30 days", callback_data="analytics:30"),
         InlineKeyboardButton("📊 All-time", callback_data="analytics:0")],
        [InlineKeyboardButton("🏠 Seller Center", callback_data="menu:sell")]
    ])

# --------------------------------------------------
#  ANALYTICS 
# --------------------------------------------------

async def show_analytics(update, context, days: int = 30):
    """Callback: display analytics panel."""
    q = update.callback_query
    seller_uid = update.effective_user.id

    data = _seller_analytics(seller_uid, days)

    text = (
        f"📈 *Seller Analytics*  –  {data['period']}\n\n"
        f"• *Active listings:* {data['active']}\n"
        f"• *Total orders:* {data['orders']}\n"
        f"• *Completed:* {data['completed']}\n"
        f"• *Conversion:* {data['conv_rate']} %\n"
        f"• *Units sold:* {data['units']}\n"
        f"• *Revenue:* ${data['revenue']:.2f}\n"
        f"• *Top SKU:* `{data['top_sku'] or 'N/A'}`"
    )

    await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                              reply_markup=_analytics_kb())
    


async def show_single_product_analytics(update, context, sku: str):
    q = update.callback_query
    seller_uid = update.effective_user.id

    # build stats 
    orders = storage.get_seller_orders_since(seller_uid, _dt.date.min)
    completed = [o for o in orders if o.get("status") == "completed" and o.get("sku") == sku]
    revenue = sum(float(o["total"]) for o in completed)
    units   = sum(int(o["qty"]) for o in completed)
    item = shopping_cart.get_any_product_by_sku(sku) or {}

    #  define text BEFORE using it 
    text = (
        f"📈 *Product Analytics* – `{sku}`\n\n"
        f"📦 *Name:* {item.get('name', sku)}\n"
        f"💰 *Revenue:* ${revenue:.2f}\n"
        f"📦 *Units Sold:* {units}\n"
        f"📊 *Completed Orders:* {len(completed)}"
    )

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Back to Item", callback_data=f"view_item:{sku}"),
        InlineKeyboardButton("🏠 Main Menu", callback_data="menu:main")
    ]])

    # send / edit 
    try:
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    except BadRequest as e:
        if "no text in the message" in str(e).lower():
            await context.bot.send_message(
                chat_id=q.message.chat.id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb
            )
        else:
            raise