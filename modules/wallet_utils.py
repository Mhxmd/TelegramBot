# modules/wallet_utils.py
import base58
import json
import os
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

# =========================
# Solana (solders-based)
# =========================
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solders.transaction import Transaction
from solders.message import Message

# =========================
# CONFIG
# =========================

SOLANA_DEVNET_RPC = "https://api.devnet.solana.com"
SOLANA_MAINNET_RPC = "https://api.mainnet-beta.solana.com"

# Clients
solana_devnet = Client(SOLANA_DEVNET_RPC)
solana_mainnet = Client(SOLANA_MAINNET_RPC)

# 🔒 PoC SAFETY: sending is DEVNET ONLY
solana_client = solana_devnet

WALLETS_FILE = "wallets.json"     # custodial wallets (PoC only)
WITHDRAW_STATE = {}               # in-memory FSM

logger = logging.getLogger(__name__)

# ============================================================
# Wallet creation & persistence (PoC custodial)
# ============================================================
def create_wallet():
    kp = Keypair()
    return {
        "public_key": str(kp.pubkey()),
        "private_key": base58.b58encode(bytes(kp)).decode(),
    }


def ensure_user_wallet(user_id: int):
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

# ============================================================
# On-chain balances
# ============================================================
def get_balance_devnet(public_key_str):
    try:
        from solana.rpc.api import Client
        from solders.pubkey import Pubkey
        
        client = Client("https://api.devnet.solana.com")
        pubkey = Pubkey.from_string(public_key_str)
        
        response = client.get_balance(pubkey)
        
        # Access the value attribute directly from the object
        lamports = response.value 
        sol_balance = lamports / 1_000_000_000
        return sol_balance
        
    except Exception as e:
        logger.error(f"Devnet balance error: {e}")
        return 0


def get_balance_both(pubkey: str):
    out = {"devnet": 0.0, "mainnet": 0.0}
    pk = Pubkey.from_string(pubkey)

    try:
        r = solana_devnet.get_balance(pk)
        out["devnet"] = r.value / 1e9
    except Exception as e:
        logger.error(f"Devnet balance error: {e}")

    try:
        r = solana_mainnet.get_balance(pk)
        out["mainnet"] = r.value / 1e9
    except Exception as e:
        logger.error(f"Mainnet balance error: {e}")

    return out


# ============================================================
# Deposit UI
# ============================================================
async def show_sol_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id

    wallet = ensure_user_wallet(uid)
    pub = wallet["public_key"]
    balances = get_balance_both(pub)

    text = (
        f"📥 *Your Solana Wallet*\n\n"
        f"Address:\n`{pub}`\n\n"
        f"🧪 *Devnet Balance:* `{balances['devnet']:.4f} SOL`\n"
        f"🌍 *Mainnet Balance:* `{balances['mainnet']:.4f} SOL`\n\n"
        "_Devnet is used for testing (faucet supported)._"
    )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔗 View Devnet",
                url=f"https://solscan.io/account/{pub}?cluster=devnet"
            ),
            InlineKeyboardButton(
                "🔗 View Mainnet",
                url=f"https://solscan.io/account/{pub}"
            ),
        ],
        [InlineKeyboardButton("🏠 Home", callback_data="menu:main")]
    ])

    await q.edit_message_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.MARKDOWN
    )


async def show_deposit_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_sol_address(update, context)

# ============================================================
# Withdraw FSM (DEVNET ONLY)
# ============================================================
def is_in_withdraw_flow(user_id: int) -> bool:
    return user_id in WITHDRAW_STATE


async def start_withdraw_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id

    WITHDRAW_STATE[uid] = {"step": "recipient"}

    await q.edit_message_text(
        "📤 *Withdraw SOL (Devnet)*\n\nSend the *recipient wallet address:*",
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_withdraw_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    uid = update.effective_user.id
    state = WITHDRAW_STATE.get(uid)
    if not state:
        return

    if state["step"] == "recipient":
        state["target"] = text.strip()
        state["step"] = "amount"
        await update.message.reply_text(
            "💰 Enter the *amount of SOL* to send:",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if state["step"] == "amount":
        try:
            amt = float(text)
            state["amount"] = amt
            state["step"] = "confirm"

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Confirm", callback_data="wallet:confirm_withdraw")],
                [InlineKeyboardButton("❌ Cancel", callback_data="menu:wallet")]
            ])

            await update.message.reply_text(
                f"⚠️ Send *{amt:.4f} SOL (Devnet)* to:\n`{state['target']}`",
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN,
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid amount.")


async def confirm_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    state = WITHDRAW_STATE.pop(uid, None)

    if not state:
        await q.answer("No active withdrawal.")
        return

    wallet = ensure_user_wallet(uid)
    result = send_sol(wallet["private_key"], state["target"], state["amount"])

    if isinstance(result, dict) and "error" in result:
        await q.edit_message_text(f"❌ Failed: {result['error']}")
    else:
        await q.edit_message_text(
            "✅ Transaction submitted (Devnet)!\n"
            f"[View on Solscan](https://solscan.io/account/{state['target']}?cluster=devnet)",
            parse_mode=ParseMode.MARKDOWN,
        )

# ============================================================
# Core blockchain transaction (DEVNET ONLY)
# ============================================================
def send_sol(sender_privkey: str, recipient_pubkey: str, amount_sol: float):
    try:
        # 1. Convert SOL to Lamports (1 SOL = 10^9 Lamports)
        lamports = int(amount_sol * 1_000_000_000)
        sender = Keypair.from_bytes(base58.b58decode(sender_privkey))
        to_pubkey = Pubkey.from_string(recipient_pubkey)

        # 2. Fetch the latest blockhash from the client
        blockhash_resp = solana_client.get_latest_blockhash()
        recent_blockhash = blockhash_resp.value.blockhash

        # 3. Create the transfer instruction
        # FIX: The transfer() function expects exactly one TransferParams object.
        ix = transfer(
            TransferParams(
                from_pubkey=sender.pubkey(),
                to_pubkey=to_pubkey,
                lamports=lamports
            )
        )

        # 4. Compile the message and create the transaction
        # Note: Message.new_with_blockhash is standard for legacy transactions in solders
        msg = Message.new_with_blockhash([ix], sender.pubkey(), recent_blockhash)
        
        tx = Transaction(
            from_keypairs=[sender],
            message=msg,
            recent_blockhash=recent_blockhash
        )

        # 5. Send the transaction
        response = solana_client.send_transaction(tx)
        
        # Return the transaction signature (ID) as a string
        return str(response.value) 

    except Exception as e:
        logger.error(f"send_sol error: {e}")
        return {"error": str(e)}