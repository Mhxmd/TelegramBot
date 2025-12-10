import os
import json
import logging
import pathlib
import stripe
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv

# ===========================================
# 🔧 Load ENV & Base Paths
# ===========================================
BASE_DIR = pathlib.Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()

stripe.api_key = STRIPE_SECRET_KEY

# JSON files (Bot also uses these)
ORDERS_FILE = "orders.json"
BALANCE_FILE = "balances.json"

app = FastAPI()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("server")


# ===========================================
# JSON Helpers
# ===========================================
def load_json(file):
    if not os.path.exists(file):
        return {}
    with open(file, "r") as f:
        return json.load(f)

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=2)


# ===========================================
# Create Checkout Session (Optional API)
# ===========================================
@app.post("/create_checkout_session")
async def create_checkout_session(request: Request):
    req = await request.json()

    order_id = str(req["order_id"])
    user_id = str(req["user_id"])
    amount = int(float(req["amount"]) * 100)  # to cents

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card", "paynow"],
            line_items=[{
                "price_data": {
                    "currency": "sgd",
                    "product_data": {"name": f"Order #{order_id}"},
                    "unit_amount": amount,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url="https://your-domain.com/success",
            cancel_url="https://your-domain.com/cancel",
            metadata={
                "type": "escrow_payment",
                "order_id": order_id,
                "user_id": user_id
            },
        )
        return {"checkout_url": session.url, "session_id": session.id}

    except Exception as e:
        log.error(f"Stripe error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ===========================================
# 📡 Stripe Webhook — Auto Detect Payment
# ===========================================
@app.post("/webhook")
async def webhook_received(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    # 🔐 Signature Verification
    try:
        event = stripe.Webhook.construct_event(
            payload, sig, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        log.error("⚠️ Invalid Webhook Signature:", e)
        raise HTTPException(status_code=400, detail=str(e))

    # ===============================
    # When Payment is Completed
    # ===============================
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata", {})
        order_type = metadata.get("type")

        log.info(f"💳 Stripe Payment Completed — Session {session['id']}")

        # -------------------------------------------------
        # 1) Escrow Purchase Payment
        # -------------------------------------------------
        if order_type == "escrow_payment":
            order_id = metadata.get("order_id")
            user_id = metadata.get("user_id")

            orders = load_json(ORDERS_FILE)
            modified = False

            # Search & update the order status
            for uid, order_list in orders.items():
                for o in order_list:
                    if str(o.get("id")) == order_id:
                        o["status"] = "Paid (Escrow)"
                        o["stripe_session_id"] = session["id"]
                        modified = True

            if modified:
                save_json(ORDERS_FILE, orders)
                log.info(f"🔒 Escrow Payment Locked for Order {order_id}")

                # TODO — CALL TELEGRAM BOT HTTP ENDPOINT
                # Example:
                # requests.post("http://localhost:8000/bot/payment_confirm", json={"order_id": order_id})

        # -------------------------------------------------
        # 2) Wallet Top-up Payment
        # -------------------------------------------------
        elif order_type == "wallet_topup":
            user_id = metadata.get("user_id")
            amount = session["amount_total"] / 100  # convert from cents

            balance = load_json(BALANCE_FILE)
            balance[user_id] = round(balance.get(user_id, 0) + amount, 2)
            save_json(BALANCE_FILE, balance)

            log.info(f"💰 Wallet Top-up +${amount:.2f} for User {user_id}")

    return {"status": "ok"}

# =============================================================
# HOW TO RUN:
# uvicorn server:app --reload --port 4242
#
# Stripe Webhook Forwarding:
# stripe listen --forward-to localhost:4242/webhook
# =============================================================
