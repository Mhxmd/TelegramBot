import os
import json
import logging
import pathlib
import stripe
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv

# ============================================================
# 🔧 LOAD ENV + CONFIG
# ============================================================
BASE_DIR = pathlib.Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
BOT_CALLBACK_URL = os.getenv("BOT_CALLBACK_URL", "").strip()  # optional future use

stripe.api_key = STRIPE_SECRET_KEY

ORDERS_FILE = BASE_DIR / "orders.json"
BALANCE_FILE = BASE_DIR / "balances.json"

app = FastAPI()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("server")


# ============================================================
# JSON HELPERS
# ============================================================
def load_json(path: pathlib.Path):
    if not path.exists():
        path.write_text("{}")
    with open(path, "r") as f:
        return json.load(f)


def save_json(path: pathlib.Path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ============================================================
# CHECKOUT SESSION (OPTIONAL API - Used by bot)
# ============================================================
@app.post("/create_checkout_session")
async def create_checkout_session(request: Request):
    body = await request.json()

    order_id = str(body["order_id"])
    user_id = str(body["user_id"])
    amount = int(float(body["amount"]) * 100)  # Stripe uses cents

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card", "paynow"],
            line_items=[
                {
                    "price_data": {
                        "currency": "sgd",
                        "product_data": {"name": f"Order #{order_id}"},
                        "unit_amount": amount,
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",

            # These MUST be real HTTPS URLs or Stripe will error.
            success_url="https://google.com",
            cancel_url="https://google.com",

            metadata={
                "type": "escrow_payment",
                "order_id": order_id,
                "user_id": user_id,
            },
        )

        log.info(f"Created Stripe session for order {order_id}")

        return {
            "checkout_url": session.url,
            "session_id": session.id
        }

    except Exception as e:
        log.error(f"⚠️ Stripe Checkout Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 📡 STRIPE WEBHOOK HANDLER — Handles all Stripe events
# ============================================================
@app.post("/webhook")
async def webhook_handler(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    # 🔐 Validate the webhook signature
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        log.error(f"❌ Invalid Webhook Signature: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    event_type = event["type"]
    session = event["data"]["object"]
    metadata = session.get("metadata", {})

    log.info(f"📡 Stripe Event Received: {event_type}")

    # ========================================================
    # PROCESS SUCCESSFUL CHECKOUT PAYMENT
    # ========================================================
    if event_type == "checkout.session.completed":
        order_type = metadata.get("type")

        # ----------------------------------------------------
        # 🔒 ESCROW PAYMENT FLOW
        # ----------------------------------------------------
        if order_type == "escrow_payment":
            order_id = metadata.get("order_id")
            user_id  = metadata.get("user_id")

            log.info(f"💳 Escrow Payment Completed — Order {order_id}")

            orders = load_json(ORDERS_FILE)
            updated = False

            # Locate and update the correct order
            for uid, user_orders in orders.items():
                for o in user_orders:
                    if str(o.get("id")) == order_id:
                        o["status"] = "Paid"
                        o["stripe_session_id"] = session["id"]
                        updated = True

            if updated:
                save_json(ORDERS_FILE, orders)
                log.info(f"🔒 Updated Escrow Order {order_id} → Paid")
            else:
                log.warning(f"⚠️ Order {order_id} not found in orders.json")

            # Optional: notify your Telegram bot server
            # if BOT_CALLBACK_URL:
            #     requests.post(f"{BOT_CALLBACK_URL}/stripe_paid", json={"order_id": order_id})

        # ----------------------------------------------------
        # 💰 WALLET TOP-UP FLOW
        # ----------------------------------------------------
        if order_type == "wallet_topup":
            user_id = metadata.get("user_id")
            amount = session["amount_total"] / 100

            balances = load_json(BALANCE_FILE)
            balances[user_id] = round(balances.get(user_id, 0) + amount, 2)
            save_json(BALANCE_FILE, balances)

            log.info(f"💰 Wallet Top-up +${amount:.2f} → User {user_id}")

    return {"status": "success"}


# ============================================================
# RUN:
# uvicorn server:app --reload --port 4242
# stripe listen --forward-to localhost:4242/webhook
# ============================================================
