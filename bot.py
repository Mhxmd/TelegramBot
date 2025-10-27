# ==========================
# Imports all the tools needed
# os,time,json,logging - python
# stripe: for card payments via stripe API
# dotenv: loads hidden keys from .env file
# qrcode: generates PAYNOW QR codes
# You can add more imports if you add extra features (like a database or wallet API)
# ==========================

import os
import time
import json
import logging
import stripe
from io import BytesIO
from dotenv import load_dotenv
import qrcode
from telegram import (
    Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ==========================
# CONFIG & SECURITY SETUP
# Loads sensitive values from the .env file to avoid hardcoding
#If you add new API's, add them here
# ==========================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()

stripe.api_key = STRIPE_SECRET_KEY

user_order_state = {}
last_message_time = {}
user_ui_msg = {}

# ==========================
# Basically creates a file called balances.json the first time the bot runs
# Stores every user's balance permanently, basically a mini database
# Can rename if needed
# To be replaced with a real database like SQLite or Firebase
# ==========================
BALANCE_FILE = "balances.json"
if not os.path.exists(BALANCE_FILE):
    with open(BALANCE_FILE, "w") as f:
        json.dump({}, f)

PRODUCTS = {
    "cat": {"name": "Cat", "price": 15, "emoji": "🐱"},
    "hoodie": {"name": "Hoodie", "price": 30, "emoji": "🧥"},
    "blackcap": {"name": "Black Cap", "price": 12, "emoji": "🧢"},
}

logging.basicConfig(
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("shopbot")

# ==========================
# BALANCE HELPERS
# def load_balances(): It reads the current balance from the file
# def save_balances(balances): It writes updated balances to the file
# def get_balance(user_id): It checks the user's balance
# def update_balance(user_id, delta): It increases/decreases the balance

# Can change currency display ( USD --> SGD )
# Add transaction history or "last updated" timestamp later
# ==========================
def load_balances():
    with open(BALANCE_FILE, "r") as f:
        return json.load(f)

def save_balances(balances):
    with open(BALANCE_FILE, "w") as f:
        json.dump(balances, f, indent=2)

def get_balance(user_id):
    balances = load_balances()
    return balances.get(str(user_id), 0.0)

def update_balance(user_id, delta):
    balances = load_balances()
    balances[str(user_id)] = round(balances.get(str(user_id), 0.0) + delta, 2)
    save_balances(balances)

# ==========================
# Helper Functions
#def is_spamming(user_id, cooldown):
#def generate_paynow_qr(amount, name = "TestBotShop")): Creates a PayNow QR image for local payments
#def clamp_qty(qty): It prevents invalid quantities ( like 0 or 9999 )
# U can edit the spam cooldown / modify the paynow QR format 
# ==========================
def is_spamming(user_id, cooldown=1.5):
    now = time.time()
    if (now - last_message_time.get(user_id, 0)) < cooldown:
        return True
    last_message_time[user_id] = now
    return False

def generate_paynow_qr(amount, name="TestBotShop"):
    data = f"PayNow to {name} - Amount: ${amount}"
    img = qrcode.make(data)
    bio = BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return bio

def clamp_qty(qty): return max(1, min(qty, 99))

# ==========================
# Bot interface
# Build_main_menu : Shows the main dashboard ( SHop, Orders, Settings, Help)
# Build_shop_keyboard: Lists available products
# Build_qty_keyboard: Lets users adjust quantity before checkout
# ==========================
def build_main_menu(balance):
    buttons = [
        [InlineKeyboardButton("🛍️ Shop", callback_data="menu:shop"),
         InlineKeyboardButton("📦 My Orders", callback_data="menu:orders")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings"),
         InlineKeyboardButton("💬 Help", callback_data="menu:help")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="menu:refresh")]
    ]
    return InlineKeyboardMarkup(buttons), (
        f"👋 *Welcome to TestBotShop!*\n\n"
        f"💰 Balance: ${balance:.2f}\n"
        "—\nUse the buttons below to browse or order:"
    )

def build_shop_keyboard():
    lines, rows = [], []
    for sku, item in PRODUCTS.items():
        lines.append(f"{item['emoji']} *{item['name']}* — ${item['price']}")
        rows.append([InlineKeyboardButton(f"Buy {item['name']} (${item['price']})",
                                          callback_data=f"buy:{sku}:1")])
    lines.append("\nTap below to order 👇")
    return "🛍️ *Our Products*\n\n" + "\n".join(lines), InlineKeyboardMarkup(rows)

def build_qty_keyboard(sku, qty):
    qty = clamp_qty(qty)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("−", callback_data=f"qty:{sku}:{qty-1}"),
            InlineKeyboardButton(f"Qty: {qty}", callback_data="noop"),
            InlineKeyboardButton("+", callback_data=f"qty:{sku}:{qty+1}")
        ],
        [InlineKeyboardButton("✅ Checkout", callback_data=f"checkout:{sku}:{qty}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_shop")]
    ])

# ==========================
# COMMAND HANDLERS
# /start shows the welcome screen and the current wallet balance
# /shop lists all products
# ==========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = get_balance(user_id)
    kb, text = build_main_menu(balance)
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = build_shop_keyboard()
    await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

# ==========================
# MENU NAVIGATION FIX
# Added to make the buttons actually respond and lead somewhere
# ==========================
async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data.split(":")[1]
    user_id = update.effective_user.id
    balance = get_balance(user_id)

    if data == "shop":
        text, kb = build_shop_keyboard()
        await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    elif data == "orders":
        await q.edit_message_text("📦 *My Orders*\nYou don't have any orders yet.",
                                  reply_markup=InlineKeyboardMarkup(
                                      [[InlineKeyboardButton("🏠 Back to Menu", callback_data="menu:main")]]
                                  ), parse_mode=ParseMode.MARKDOWN)
    elif data == "settings":
        await q.edit_message_text(
            "⚙️ *Settings*\n• Notifications: ON\n• Currency: USD",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Back to Menu", callback_data="menu:main")]]
            ), parse_mode=ParseMode.MARKDOWN)
    elif data == "help":
        await q.edit_message_text(
            "💬 *Help*\nContact: @yourusername\nType /start to return anytime.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 Back to Menu", callback_data="menu:main")]]
            ), parse_mode=ParseMode.MARKDOWN)
    elif data == "refresh" or data == "main":
        kb, text = build_main_menu(balance)
        await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

# ==========================
# SHOP FLOW
# ==========================
async def on_buy(update: Update, context: ContextTypes.DEFAULT_TYPE, sku, qty):
    q = update.callback_query
    await q.answer()
    item = PRODUCTS.get(sku)
    if not item:
        await q.answer("Item not found", show_alert=True)
        return
    total = item["price"] * qty
    text = f"{item['emoji']} *{item['name']}*\nQty: {qty}\nTotal: *${total}*\n\nChoose payment method:"
    buttons = [
        [InlineKeyboardButton("💳 Pay with Stripe", callback_data=f"stripe:{sku}:{qty}")],
        [InlineKeyboardButton("🇸🇬 PayNow QR", callback_data=f"paynow:{sku}:{qty}")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_shop")]
    ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode=ParseMode.MARKDOWN)

async def create_stripe_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE, sku, qty):
    q = update.callback_query
    await q.answer()
    item = PRODUCTS[sku]
    total = item["price"] * qty

    checkout = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": item["name"]},
                "unit_amount": item["price"] * 100,
            },
            "quantity": qty,
        }],
        mode="payment",
        success_url="https://example.com/success",
        cancel_url="https://example.com/cancel"
    )

    await q.edit_message_text(
        f"💳 Click below to complete your payment:\n{checkout.url}\n\n"
        f"After payment, your balance will be updated automatically.",
        parse_mode=ParseMode.MARKDOWN
    )

async def show_paynow(update: Update, context: ContextTypes.DEFAULT_TYPE, sku, qty):
    q = update.callback_query
    await q.answer()
    item = PRODUCTS[sku]
    total = item["price"] * qty
    qr_img = generate_paynow_qr(total)
    await q.message.reply_photo(photo=InputFile(qr_img, filename="paynow.png"),
                                caption=f"🇸🇬 PayNow ${total}\nSend proof after payment.",
                                parse_mode=ParseMode.MARKDOWN)

# ==========================
# CALLBACK ROUTER
# The bot receives a callback query event 
# The router reads data = q.data
# It checks what the data starts with ( buy;, stripe, paynow: etc)
# Then decides which helper function to call
# The function updates the message or sends new info to the new user
# ==========================
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data.startswith("menu:"):
        await on_menu(update, context)
    elif data.startswith("buy:"):
        _, sku, qty = data.split(":")
        await on_buy(update, context, sku, int(qty))
    elif data.startswith("stripe:"):
        _, sku, qty = data.split(":")
        await create_stripe_checkout(update, context, sku, int(qty))
    elif data.startswith("paynow:"):
        _, sku, qty = data.split(":")
        await show_paynow(update, context, sku, int(qty))
    elif data == "back_to_shop":
        text, kb = build_shop_keyboard()
        await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

# ==========================
# MAIN
# Main bot functions
# ==========================
def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN not found in .env")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("shop", shop))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_error_handler(lambda u, c: logger.error(c.error))
    print("🤖 Bot running — press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
