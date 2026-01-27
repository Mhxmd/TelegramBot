# modules/wallet_utils.py
import base58
import json
import os
import logging
from typing import Dict, Optional, Union

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# ---------- Solana ----------
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solders.transaction import Transaction
from solders.message import Message

# ---------- config ----------
SOLANA_DEVNET_RPC  = "https://api.devnet.solana.com"
SOLANA_MAINNET_RPC = "https://api.mainnet-beta.solana.com"

NETWORK = os.getenv("SOLANA_NETWORK", "devnet").lower()
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL",
                           SOLANA_MAINNET_RPC if NETWORK == "mainnet" else SOLANA_DEVNET_RPC)

devnet_client  = Client(SOLANA_DEVNET_RPC)
mainnet_client = Client(SOLANA_MAINNET_RPC)
solana_client  = Client(SOLANA_RPC_URL)

WALLETS_FILE   = "wallets.json"
WITHDRAW_STATE: Dict[int, dict] = {}

logger = logging.getLogger(__name__)
NETWORK_NAMES = {"devnet": "🧪 Devnet (Test)", "mainnet": "🌍 Mainnet (Real SOL)"}

# ---------- wallet life-cycle ----------
def create_wallet() -> Dict[str, str]:
    kp = Keypair()
    return {"public_key": str(kp.pubkey()), "private_key": base58.b58encode(bytes(kp)).decode()}

def ensure_user_wallet(user_id: int) -> Dict[str, str]:
    os.makedirs(os.path.dirname(WALLETS_FILE) or ".", exist_ok=True)
    if not os.path.exists(WALLETS_FILE):
        with open(WALLETS_FILE, "w") as f:
            json.dump({}, f)

    with open(WALLETS_FILE, "r") as f:
        data: dict = json.load(f)

    uid = str(user_id)
    if uid not in data:
        data[uid] = create_wallet()
        with open(WALLETS_FILE, "w") as f:
            json.dump(data, f, indent=2)

    return data[uid]

# ---------- balances ----------
def get_balance(pubkey: str, network: Optional[str] = None) -> float:
    network = network or NETWORK
    client  = mainnet_client if network == "mainnet" else devnet_client
    try:
        return client.get_balance(Pubkey.from_string(pubkey)).value / 1e9
    except Exception as e:
        logger.error("get_balance (%s) → %s", network, e)
        return 0.0

def get_balance_both(pubkey: str) -> Dict[str, float]:
    return {"devnet": get_balance(pubkey, "devnet"), "mainnet": get_balance(pubkey, "mainnet")}

def get_balance_devnet(pubkey: str) -> float:
    return get_balance(pubkey, "devnet")

def get_balance_mainnet(pubkey: str) -> float:
    return get_balance(pubkey, "mainnet")

# ---------- UI helpers ----------
async def show_sol_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    wallet   = ensure_user_wallet(uid)
    balances = get_balance_both(wallet["public_key"])

    text = (f"📥 *Your Solana Wallet*\n"
            f"Network: `{NETWORK_NAMES[NETWORK]}`\n\n"
            f"`{wallet['public_key']}`\n\n"
            f"🧪 Devnet:  `{balances['devnet']:.4f}` SOL\n"
            f"🌍 Mainnet: `{balances['mainnet']:.4f}` SOL\n\n") + \
           ("_Real money on Mainnet – send only to addresses you trust._" if NETWORK == "mainnet" else "_Use a devnet faucet for free test-SOL._")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Withdraw", callback_data="wallet:withdraw"),
         InlineKeyboardButton("🔧 Network", callback_data="wallet:network")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")]
    ])
    await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)

async def show_deposit_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_sol_address(update, context)

# ------------------------------------------------------------------
#  DUAL-NETWORK  WITHDRAW  (NEW)
# ------------------------------------------------------------------
WITHDRAW_STATE: Dict[int, dict] = {}

async def start_withdraw_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show two buttons :  Test-Net  vs  Live-Net"""
    q = update.callback_query
    uid = update.effective_user.id
    wallet = ensure_user_wallet(uid)
    both = get_balance_both(wallet["public_key"])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Withdraw SOL (Devnet – Test)", callback_data="withdraw:devnet")],
        [InlineKeyboardButton("🌍 Withdraw SOL (Mainnet – Real)", callback_data="withdraw:mainnet")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu:wallet")]
    ])

    text = (f"💸 *Choose Network*\n\n"
            f"🧪 Devnet balance: `{both['devnet']:.4f}` SOL  (free test-SOL)\n"
            f"🌍 Mainnet balance: `{both['mainnet']:.4f}` SOL  (real money)")
    await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

async def handle_withdraw_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    _, network = q.data.split(":")          # "withdraw:devnet"  etc.

    wallet = ensure_user_wallet(uid)
    bal = get_balance(wallet["public_key"], network)

    # ➜  diagnostic log
    logger.info("💰 %s balance for uid %s = %.6f SOL", network, uid, bal)

    if bal <= 0:
        await q.answer(f"❌ Zero balance on {NETWORK_NAMES[network]}", show_alert=True)
        return

    WITHDRAW_STATE[uid] = {"step": "recipient", "balance": bal, "network": network}
    warning = ("\n\n⚠️ **MAINNET WITHDRAWAL** – real money.\n"
               "Transactions are irreversible. Double-check address.") if network == "mainnet" else ""

    await q.edit_message_text(
        f"📤 *Withdraw SOL ({NETWORK_NAMES[network]})*{warning}\n\n"
        f"Available: `{bal:.4f}` SOL\n\n"
        "Send the **recipient wallet address**:",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_withdraw_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    uid = update.effective_user.id
    state = WITHDRAW_STATE.get(uid)
    if not state: return

    if state["step"] == "recipient":
        try:
            Pubkey.from_string(text.strip())
            state["target"] = text.strip()
            state["step"]   = "amount"
            await update.message.reply_text("💰 Enter the **amount of SOL** to send:", parse_mode=ParseMode.MARKDOWN)
        except: await update.message.reply_text("❌ Invalid Solana address.")
        return

    if state["step"] == "amount":
        try:
            amt = float(text)
            if amt <= 0: raise ValueError("positive number")
            fee_buffer = 0.001 if state["network"] == "mainnet" else 0.0001
            if amt > state["balance"] - fee_buffer:
                await update.message.reply_text(
                    f"❌ Insufficient balance.\n"
                    f"Available: `{state['balance']:.4f}` SOL\n"
                    f"Max you can send: ~`{state['balance'] - fee_buffer:.4f}` SOL"
                )
                return

            state["amount"] = amt
            state["step"]   = "confirm"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm Send", callback_data="wallet:confirm_withdraw")],
                [InlineKeyboardButton("❌ Cancel",      callback_data="menu:wallet")]
            ])
            warning = ("\n\n🚨 **REAL SOL** – cannot be cancelled." if state["network"] == "mainnet" else "")
            await update.message.reply_text(
                f"📤 *Summary*{warning}\n"
                f"Amount: `{amt:.4f}` SOL\n"
                f"To: `{state['target']}`",
                reply_markup=kb, parse_mode=ParseMode.MARKDOWN
            )
        except: await update.message.reply_text("❌ Invalid amount.")

async def confirm_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    state = WITHDRAW_STATE.pop(uid, None)
    if not state:
        await q.answer("No active withdrawal", show_alert=True); return

    wallet = ensure_user_wallet(uid)
    sig = send_sol(wallet["private_key"], state["target"], state["amount"], network=state["network"])

    explorer = "" if state["network"] == "mainnet" else "?cluster=devnet"
    if isinstance(sig, dict) and "error" in sig:
        await q.edit_message_text(f"❌ Failed: `{sig['error']}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await q.edit_message_text(
            "✅ Transaction submitted!\n"
            f"[View on Solscan](https://solscan.io/tx/{sig}{explorer})",
            parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
        )

def send_sol(private_key_b58: str, to_pubkey: str, amount_sol: float, network: str) -> Union[str, dict]:
    client = mainnet_client if network == "mainnet" else devnet_client
    try:
        lamports  = int(amount_sol * 1e9)
        sender    = Keypair.from_bytes(base58.b58decode(private_key_b58))
        recipient = Pubkey.from_string(to_pubkey)

        blockhash = client.get_latest_blockhash().value.blockhash
        ix = transfer(TransferParams(from_pubkey=sender.pubkey(), to_pubkey=recipient, lamports=lamports))

        msg = Message.new_with_blockhash([ix], sender.pubkey(), blockhash)
        tx = Transaction([sender], msg, blockhash)

        return str(client.send_transaction(tx).value)
    except Exception as e:
        logger.exception("send_sol (%s)", network)
        return {"error": str(e)}

# ---------- utilities ----------
def get_network() -> str:
    return NETWORK

def is_mainnet() -> bool:
    return NETWORK == "mainnet"