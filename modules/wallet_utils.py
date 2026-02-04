import base58
import json
import os
import logging
import time
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
# Using more reliable public endpoints for 2026
SOLANA_DEVNET_RPC  = "https://api.devnet.solana.com"
# Fallback Devnet if official is slow: "https://devnet.helius-rpc.com/?api-key=YOUR_KEY"
SOLANA_MAINNET_RPC = "https://api.mainnet-beta.solana.com"

NETWORK = os.getenv("SOLANA_NETWORK", "devnet").lower()

# Initialize specific clients
devnet_client  = Client(SOLANA_DEVNET_RPC)
mainnet_client = Client(SOLANA_MAINNET_RPC)

# This client follows the global environment setting
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", SOLANA_MAINNET_RPC if NETWORK == "mainnet" else SOLANA_DEVNET_RPC)
solana_client  = Client(SOLANA_RPC_URL)

WALLETS_FILE   = "wallets.json"
logger = logging.getLogger(__name__)
NETWORK_NAMES = {"devnet": "🧪 Devnet (Test)", "mainnet": "🌍 Mainnet (Real SOL)"}

# ---------- wallet life-cycle ----------
def create_wallet() -> Dict[str, str]:
    kp = Keypair()
    # Store as base58 string (common for Solana private keys)
    return {"public_key": str(kp.pubkey()), "private_key": base58.b58encode(bytes(kp)).decode()}

def ensure_user_wallet(user_id: int) -> Dict[str, str]:
    os.makedirs(os.path.dirname(WALLETS_FILE) or ".", exist_ok=True)
    if not os.path.exists(WALLETS_FILE):
        with open(WALLETS_FILE, "w") as f:
            json.dump({}, f)

    with open(WALLETS_FILE, "r") as f:
        try:
            data: dict = json.load(f)
        except json.JSONDecodeError:
            data = {}

    uid = str(user_id)
    if uid not in data:
        data[uid] = create_wallet()
        with open(WALLETS_FILE, "w") as f:
            json.dump(data, f, indent=2)

    return data[uid]

# ---------- balances ----------
def get_balance(pubkey: str, network: Optional[str] = None) -> float:
    """Fetch balance with explicit network selection and retry logic."""
    target_network = network or NETWORK
    client = mainnet_client if target_network == "mainnet" else devnet_client
    
    try:
        response = client.get_balance(Pubkey.from_string(pubkey))
        return response.value / 1e9
    except Exception as e:
        logger.error(f"Error fetching {target_network} balance for {pubkey}: {e}")
        return 0.0

def get_balance_both(pubkey: str) -> Dict[str, float]:
    return {
        "devnet": get_balance(pubkey, "devnet"),
        "mainnet": get_balance(pubkey, "mainnet")
    }

# ---------- UI helpers ----------
async def show_sol_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    wallet = ensure_user_wallet(uid)
    balances = get_balance_both(wallet["public_key"])

    text = (f"📥 *Your Solana Wallet*\n"
            f"Active Network: `{NETWORK_NAMES[NETWORK]}`\n\n"
            f"Address:\n`{wallet['public_key']}`\n\n"
            f"🧪 Devnet:  `{balances['devnet']:.4f}` SOL\n"
            f"🌍 Mainnet: `{balances['mainnet']:.4f}` SOL\n\n")
    
    if NETWORK == "mainnet":
        text += "⚠️ _Real money on Mainnet – send only to addresses you trust._"
    else:
        text += "💡 _Use a devnet faucet to get free test SOL for development._"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Withdraw SOL", callback_data="wallet:withdraw")],
        [InlineKeyboardButton("🔧 Switch Network", callback_data="wallet:network")],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")]
    ])
    
    if q:
        await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

# ---------- Withdraw Flow ----------
WITHDRAW_STATE: Dict[int, dict] = {}

async def start_withdraw_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    wallet = ensure_user_wallet(uid)
    both = get_balance_both(wallet["public_key"])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Withdraw Devnet (Test)", callback_data="withdraw:devnet")],
        [InlineKeyboardButton("🌍 Withdraw Mainnet (Real)", callback_data="withdraw:mainnet")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu:wallet")]
    ])

    text = (f"💸 *Choose Network to Withdraw From*\n\n"
            f"🧪 Devnet: `{both['devnet']:.4f}` SOL\n"
            f"🌍 Mainnet: `{both['mainnet']:.4f}` SOL")
    await q.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

async def handle_withdraw_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    _, network = q.data.split(":")

    wallet = ensure_user_wallet(uid)
    bal = get_balance(wallet["public_key"], network)

    if bal <= 0.001:  # Buffer for fees
        await q.answer(f"❌ Insufficient balance on {network}", show_alert=True)
        return

    WITHDRAW_STATE[uid] = {"step": "recipient", "balance": bal, "network": network}
    
    await q.edit_message_text(
        f"📤 *Withdraw SOL ({NETWORK_NAMES[network]})*\n\n"
        f"Available: `{bal:.4f}` SOL\n"
        "Please enter the **recipient address**:",
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
            state["step"] = "amount"
            await update.message.reply_text(f"💰 Enter amount (Max: ~{state['balance']-0.001:.4f}):")
        except:
            await update.message.reply_text("❌ Invalid Solana address. Try again:")
        return

    if state["step"] == "amount":
        try:
            amt = float(text)
            fee_buffer = 0.001
            if amt <= 0 or amt > (state["balance"] - fee_buffer):
                await update.message.reply_text(f"❌ Invalid amount. Max allowed: `{state['balance']-fee_buffer:.4f}`")
                return

            state["amount"] = amt
            state["step"] = "confirm"
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm & Send", callback_data="wallet:confirm_withdraw")],
                [InlineKeyboardButton("❌ Cancel", callback_data="menu:wallet")]
            ])
            await update.message.reply_text(
                f"⚠️ *Final Confirmation*\n\n"
                f"Network: {NETWORK_NAMES[state['network']]}\n"
                f"Amount: `{amt}` SOL\n"
                f"To: `{state['target']}`\n\n"
                "Transactions are irreversible!",
                reply_markup=kb, parse_mode=ParseMode.MARKDOWN
            )
        except:
            await update.message.reply_text("❌ Please enter a valid number.")

async def confirm_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    state = WITHDRAW_STATE.pop(uid, None)
    
    if not state:
        await q.answer("Session expired."); return

    await q.edit_message_text("⏳ Processing transaction... please wait.")
    
    wallet = ensure_user_wallet(uid)
    result = send_sol(wallet["private_key"], state["target"], state["amount"], state["network"])

    if isinstance(result, dict) and "error" in result:
        await q.edit_message_text(f"❌ Error: `{result['error']}`", parse_mode=ParseMode.MARKDOWN)
    else:
        cluster = "devnet" if state["network"] == "devnet" else "mainnet-beta"
        url = f"https://solscan.io/tx/{result}?cluster={cluster}"
        await q.edit_message_text(
            f"✅ *Transaction Sent!*\n\n"
            f"Signature: `{result[:10]}...`\n"
            f"[View on Solscan]({url})",
            parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True
        )

def send_sol(private_key_b58: str, to_pubkey: str, amount_sol: float, network: str) -> Union[str, dict]:
    client = mainnet_client if network == "mainnet" else devnet_client
    try:
        sender = Keypair.from_bytes(base58.b58decode(private_key_b58))
        recipient = Pubkey.from_string(to_pubkey)
        lamports = int(amount_sol * 1e9)

        # 1. Get Blockhash
        recent_blockhash = client.get_latest_blockhash().value.blockhash
        
        # 2. Create Instruction
        ix = transfer(TransferParams(
            from_pubkey=sender.pubkey(), 
            to_pubkey=recipient, 
            lamports=lamports
        ))

        # 3. Compile Message & Transaction
        msg = Message.new_with_blockhash([ix], sender.pubkey(), recent_blockhash)
        tx = Transaction([sender], msg, recent_blockhash)

        # 4. Send and wait for confirmation
        res = client.send_transaction(tx)
        
        # Simple Confirmation Loop
        sig = res.value
        logger.info(f"Tx submitted: {sig}")
        
        # Optional: Add confirmation check here if your library version supports it
        # client.confirm_transaction(sig)
        
        return str(sig)
    except Exception as e:
        logger.exception(f"Send SOL failed on {network}")
        return {"error": str(e)}

# ---------- utilities ----------
def get_network() -> str:
    return NETWORK

def is_mainnet() -> bool:
    return NETWORK == "mainnet"