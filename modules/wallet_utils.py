# modules/wallet_utils.py
import base58
import json
import os
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram import Update
from telegram.ext import ContextTypes

# Auto-detect Solana SDK version
try:
    from solana.rpc.api import Client
    from solana.keypair import Keypair
    from solana.system_program import TransferParams, transfer
    from solana.transaction import Transaction
    MODE = "old"
except ImportError:
    from solana.rpc.api import Client
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey
    from solders.system_program import transfer
    from solders.transaction import Transaction
    MODE = "new"

SOLANA_RPC = "https://api.mainnet-beta.solana.com"
solana_client = Client(SOLANA_RPC)
logger = logging.getLogger(__name__)

WALLETS_FILE = "wallets.json"
WITHDRAW_STATE = {}  # in-memory: user_id → {"step":..., "target":..., "amount":...}


# --------------------------------------------------------------------------
# Helpers for wallet creation and persistence
# --------------------------------------------------------------------------
def create_wallet():
    kp = Keypair()
    try:
        pub = str(kp.public_key)
        priv = base58.b58encode(kp.secret_key).decode()
    except Exception:
        pub = str(kp.pubkey())
        priv = base58.b58encode(bytes(kp)).decode()
    return {"public_key": pub, "private_key": priv}


def ensure_user_wallet(user_id: int):
    """Load or create a wallet for the given Telegram user."""
    if not os.path.exists(WALLETS_FILE):
        with open(WALLETS_FILE, "w") as f:
            json.dump({}, f)
    with open(WALLETS_FILE, "r") as f:
        data = json.load(f)
    uid = str(user_id)
    if uid not in data:
        data[uid] = create_wallet()
        with open(WALLETS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    return data[uid]


def get_balance_sol(pubkey: str) -> float:
    try:
        resp = solana_client.get_balance(pubkey)
        lamports = resp.get("result", {}).get("value", 0)
        return lamports / 1e9
    except Exception as e:
        logger.error(f"Error getting balance: {e}")
        return 0.0


# --------------------------------------------------------------------------
# Deposit / Withdraw Handlers for bot.py
# --------------------------------------------------------------------------
async def show_sol_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the user's Solana deposit address + current on-chain balance."""
    q = update.callback_query
    uid = update.effective_user.id
    wallet = ensure_user_wallet(uid)
    pub = wallet["public_key"]
    bal = get_balance_sol(pub)
    text = (
        f"📥 *Your Solana Wallet*\n\n"
        f"Address:\n`{pub}`\n"
        f"Balance: *{bal:.4f} SOL*\n\n"
        "You can deposit SOL or USDC (SPL) to this address."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 View on Solscan",
                      url=f"https://solscan.io/account/{pub}")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:main")],
    ])
    await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)


async def show_deposit_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias to show_sol_address (for /wallet:deposit)."""
    await show_sol_address(update, context)


# --------------------------------------------------------------------------
# Withdraw flow: ask user → recipient → amount → confirm
# --------------------------------------------------------------------------
def is_in_withdraw_flow(user_id: int) -> bool:
    return user_id in WITHDRAW_STATE


async def start_withdraw_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start withdrawal conversation."""
    q = update.callback_query
    uid = update.effective_user.id
    WITHDRAW_STATE[uid] = {"step": "recipient"}
    await q.edit_message_text(
        "📤 *Withdraw SOL*\n\nPlease send the *recipient wallet address*:",
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_withdraw_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Handle the conversation steps."""
    uid = update.effective_user.id
    state = WITHDRAW_STATE.get(uid)
    if not state:
        return

    # Step 1 → got recipient
    if state["step"] == "recipient":
        state["target"] = text.strip()
        state["step"] = "amount"
        await update.message.reply_text(
            "💰 Enter the *amount of SOL* to send:", parse_mode=ParseMode.MARKDOWN
        )
        return

    # Step 2 → got amount
    elif state["step"] == "amount":
        try:
            amt = float(text)
            state["amount"] = amt
            state["step"] = "confirm"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data=f"wallet:confirm_withdraw")],
                [InlineKeyboardButton("❌ Cancel", callback_data=f"menu:wallet")]
            ])
            await update.message.reply_text(
                f"⚠️ You are about to send *{amt:.4f} SOL* to `{state['target']}`.\n"
                "Tap *Confirm* to proceed.",
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid amount. Try again.")
        return


async def confirm_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Execute send_sol() when user confirms withdrawal."""
    q = update.callback_query
    uid = update.effective_user.id
    state = WITHDRAW_STATE.pop(uid, None)
    if not state:
        await q.answer("No active withdrawal.")
        return

    wallet = ensure_user_wallet(uid)
    sender_priv = wallet["private_key"]
    target = state["target"]
    amount = state["amount"]

    await q.edit_message_text(f"🚀 Sending {amount:.4f} SOL to `{target}` ...",
                              parse_mode=ParseMode.MARKDOWN)
    result = send_sol(sender_priv, target, amount)
    if isinstance(result, dict) and "error" in result:
        await q.message.reply_text(f"❌ Failed: {result['error']}")
    else:
        await q.message.reply_text(
    "✅ Transaction submitted successfully!\n"
    f"🔗 [View on Solscan](https://solscan.io/account/{target})",
    parse_mode=ParseMode.MARKDOWN
)

# --------------------------------------------------------------------------
# Core transaction function (shared)
# --------------------------------------------------------------------------
def send_sol(sender_privkey: str, recipient_pubkey: str, amount_sol: float):
    try:
        if MODE == "old":
            sender = Keypair.from_secret_key(base58.b58decode(sender_privkey))
            txn = Transaction()
            txn.add(transfer(TransferParams(
                from_pubkey=sender.public_key,
                to_pubkey=recipient_pubkey,
                lamports=int(amount_sol * 1e9)
            )))
            result = solana_client.send_transaction(txn, sender)
        else:
            sender = Keypair.from_bytes(base58.b58decode(sender_privkey))
            to_pubkey = Pubkey.from_string(recipient_pubkey)
            txn = Transaction().add(transfer(sender.pubkey(), to_pubkey, int(amount_sol * 1e9)))
            result = solana_client.send_transaction(txn, sender)
        return result
    except Exception as e:
        logger.error(f"send_sol error: {e}")
        return {"error": str(e)}
