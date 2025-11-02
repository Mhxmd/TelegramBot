# ==========================
# 💼 wallet_utils.py — Solana wallet helper
# Handles:
# - Creating new wallets (public/private keypairs)
# - Sending SOL transactions
# - Checking balances
# ==========================

import base58
import logging
from solders.keypair import Keypair # type: ignore
from solders.pubkey import Pubkey # type: ignore
from solders.system_program import TransferParams, transfer
from solana.rpc.api import Client
from solana.transaction import Transaction

# ==========================
# CONFIGURATION
# ==========================
SOLANA_RPC = "https://api.mainnet-beta.solana.com"  # use mainnet or devnet
solana_client = Client(SOLANA_RPC)

# Enable logging for debugging
logger = logging.getLogger("wallet_utils")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ==========================
# 🪙 CREATE WALLET
# ==========================
def create_wallet():
    """
    Creates a new Solana wallet and returns both the public key and private key.
    The private key is base58 encoded for easier storage.
    """
    kp = Keypair()
    pubkey = str(kp.pubkey())
    privkey = base58.b58encode(bytes(kp)).decode()
    logger.info(f"✅ Created wallet: {pubkey}")
    return {
        "public_key": pubkey,
        "private_key": privkey
    }


# ==========================
# 💸 SEND SOL TRANSACTION
# ==========================
def send_sol(sender_privkey: str, recipient_pubkey: str, amount_sol: float):
    """
    Sends SOL from one wallet to another.

    Args:
        sender_privkey (str): Sender's private key (base58 encoded)
        recipient_pubkey (str): Recipient's public key (string)
        amount_sol (float): Amount in SOL to send

    Returns:
        dict: Transaction result or error message
    """
    try:
        sender = Keypair.from_bytes(base58.b58decode(sender_privkey))
        recipient = Pubkey.from_string(recipient_pubkey)
        lamports = int(amount_sol * 1_000_000_000)

        # Build and sign transaction
        txn = Transaction().add(transfer(TransferParams(
            from_pubkey=sender.pubkey(),
            to_pubkey=recipient,
            lamports=lamports
        )))

        result = solana_client.send_transaction(txn, sender)
        logger.info(f"✅ Sent {amount_sol} SOL to {recipient_pubkey}")
        return result

    except Exception as e:
        logger.error(f"❌ Transaction failed: {e}")
        return {"error": str(e)}


# ==========================
# 💰 CHECK BALANCE
# ==========================
def get_balance(pubkey: str):
    """
    Fetches the current SOL balance for a given public key.

    Args:
        pubkey (str): Wallet public key

    Returns:
        float: Balance in SOL
    """
    try:
        resp = solana_client.get_balance(Pubkey.from_string(pubkey))
        lamports = resp["result"]["value"]
        sol = lamports / 1_000_000_000
        return sol
    except Exception as e:
        logger.error(f"❌ Failed to fetch balance: {e}")
        return 0.0
