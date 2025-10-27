# ==========================
# 💳 server.py — Stripe Checkout + Webhook Handler
# Handles local payment creation (card / PayNow) and webhook verification
# ==========================

import os
import json
import logging
import stripe
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv

# ==========================
# ⚙️ CONFIGURATION
# ==========================
load_dotenv()

# Stripe secret key
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()

stripe.api_key = STRIPE_SECRET_KEY

# Local data files (optional for wallet or order tracking)
BALANCE_FILE = "balances.json"
ORDERS_FILE = "orders.json"

app = FastAPI()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

# ==========================
# 🧠 Helper Functions
# ==========================
def load_json(file):
    """Load a JSON file safely."""
    if not os.path.exists(file):
        return {}
    with open(file, "r") as f:
        return json.load(f)

def save_json(file, data):
    """Save data back to a JSON file."""
    with open(file, "w") as f:
        json.dump(data, f, indent=2)

# ==========================
# 🛒 Checkout Endpoint
# Used when creating Stripe checkout links (for testing)
# ==========================
@app.post("/create_checkout")
async def create_checkout():
    """
    Create a Stripe Checkout session.
    Supports both credit card and PayNow for SGD payments.
    """
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card', 'paynow'],
            line_items=[{
                'price_data': {
                    'currency': 'sgd',
                    'product_data': {'name': 'Example Item'},
                    'unit_amount': 1500,  # $15.00 SGD
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url='https://example.com/success',
            cancel_url='https://example.com/cancel',
        )

        logger.info(f"✅ Created checkout session: {session.url}")
        return {"checkout_url": session.url}

    except Exception as e:
        logger.error(f"❌ Error creating checkout session: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ==========================
# 📡 Stripe Webhook Listener
# Triggered automatically by Stripe after payment
# ==========================
@app.post("/webhook")
async def webhook_received(request: Request):
    """
    Stripe webhook endpoint to verify and handle payment events.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        logger.error(f"⚠️ Webhook verification failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    # ✅ Payment completed
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        logger.info(f"✅ Payment received for {session['amount_total']/100:.2f} {session['currency'].upper()}")
        logger.info(f"Session ID: {session['id']} | Customer Email: {session.get('customer_email')}")

    if session.get("metadata", {}).get("type") == "wallet_topup":
        user_id = int(session["metadata"]["user_id"])
        amount = session["amount_total"] / 100
        balances = load_json(BALANCE_FILE)
        balances[str(user_id)] = round(balances.get(str(user_id), 0) + amount, 2)
        save_json(BALANCE_FILE, balances)
        logger.info(f"💰 Wallet topped up for user {user_id} (+${amount:.2f})")


        # Optional: update local order or wallet here
        orders = load_json(ORDERS_FILE)
        for user_id, user_orders in orders.items():
            for order in user_orders:
                if order.get("stripe_session_id") == session["id"]:
                    order["status"] = "Paid"
                    save_json(ORDERS_FILE, orders)
                    logger.info(f"💰 Order marked as paid for user {user_id}")

    return {"status": "success"}

# ==========================
# 🧩 How to Run
# Run this server locally on port 4242:
# uvicorn server:app --reload --port 4242
#
# Then connect Stripe CLI:
# stripe listen --forward-to localhost:4242/webhook
# ==========================
