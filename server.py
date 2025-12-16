import os
import json
import logging
import pathlib

import stripe
from fastapi import FastAPI, Request, HTTPException
from dotenv import load_dotenv
from fastapi.responses import HTMLResponse


# ============================================================
# 🔧 LOAD ENV + CONFIG
# ============================================================
BASE_DIR = pathlib.Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip()  # e.g. https://xxxx.ngrok-free.dev
BOT_CALLBACK_URL = os.getenv("BOT_CALLBACK_URL", "").strip()  # optional future use

if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY missing in .env")
if not STRIPE_WEBHOOK_SECRET:
    raise RuntimeError("STRIPE_WEBHOOK_SECRET missing in .env")
if not PUBLIC_BASE_URL:
    raise RuntimeError("PUBLIC_BASE_URL missing in .env (use your ngrok https URL)")

stripe.api_key = STRIPE_SECRET_KEY

ORDERS_FILE = BASE_DIR / "orders.json"
BALANCE_FILE = BASE_DIR / "balances.json"

app = FastAPI()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("server")

#HTMLResponse

from fastapi.responses import HTMLResponse

@app.get("/payment/success", response_class=HTMLResponse)
async def payment_success(order_id: str):
    return f"""
    <html>
      <head>
        <meta charset="utf-8" />
        <title>Payment Successful</title>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <meta http-equiv="refresh" content="5;url=https://t.me/Xchange_ShopBot?start=success_{order_id}">
        <style>
          body {{
            background:#020617;
            color:#e5e7eb;
            font-family:system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
            display:flex;
            justify-content:center;
            align-items:center;
            height:100vh;
            margin:0;
          }}
          .card {{
            background:#020617;
            padding:36px;
            border-radius:16px;
            max-width:420px;
            text-align:center;
            box-shadow:0 20px 40px rgba(0,0,0,0.55);
            border:1px solid #1e293b;
          }}
          h1 {{
            color:#22c55e;
            margin-bottom:12px;
          }}
          p {{
            color:#cbd5f5;
            line-height:1.6;
          }}
          a {{
            display:inline-block;
            margin-top:26px;
            padding:14px 24px;
            background:#2563eb;
            color:white;
            border-radius:12px;
            text-decoration:none;
            font-weight:600;
          }}
          .hint {{
            margin-top:18px;
            font-size:0.9rem;
            opacity:0.7;
          }}
        </style>
      </head>
      <body>
        <div class="card">
          <h1>✅ Payment Successful</h1>
          <p>
            Your payment for order <b>{order_id}</b> was received.<br/>
            Funds are now secured in escrow.
          </p>

          <a href="https://t.me/Xchange_ShopBot?start=success_{order_id}">
            ⬅ Return to Xchange Bot
          </a>

          <div class="hint">
            Redirecting you back to Telegram…
          </div>
        </div>
      </body>
    </html>
    """


from fastapi.responses import HTMLResponse

@app.get("/payment/cancel", response_class=HTMLResponse)
async def payment_cancel(order_id: str):
    return f"""
    <html>
      <head>
        <meta charset="utf-8" />
        <title>Payment Cancelled</title>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <style>
          body {{
            background:#020617;
            color:#e5e7eb;
            font-family:system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
            display:flex;
            justify-content:center;
            align-items:center;
            height:100vh;
            margin:0;
          }}
          .card {{
            background:#020617;
            padding:36px;
            border-radius:16px;
            max-width:420px;
            text-align:center;
            box-shadow:0 20px 40px rgba(0,0,0,0.55);
            border:1px solid #1e293b;
          }}
          h1 {{
            color:#ef4444;
            margin-bottom:12px;
          }}
          p {{
            color:#cbd5f5;
            line-height:1.6;
          }}
          a {{
            display:inline-block;
            margin-top:26px;
            padding:14px 24px;
            background:#2563eb;
            color:white;
            border-radius:12px;
            text-decoration:none;
            font-weight:600;
          }}
        </style>
      </head>
      <body>
        <div class="card">
          <h1>❌ Payment Cancelled</h1>
          <p>
            Order <b>{order_id}</b> was not completed.
          </p>

          <a href="https://t.me/Xchange_ShopBot?start=cancel_{order_id}">
            ⬅ Return to Xchange Bot
          </a>
        </div>
      </body>
    </html>
    """





# ============================================================
# JSON HELPERS
# ============================================================
def load_json(path: pathlib.Path):
    """
    Orders format expected (dict):
    {
      "ord_123": { ...order... },
      "ord_456": { ...order... }
    }
    Balances format expected (dict):
    {
      "123456789": 10.50,
      "987654321": 2.00
    }
    """
    if not path.exists():
        path.write_text("{}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: pathlib.Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ============================================================
# HEALTH CHECK
# ============================================================
@app.get("/health")
async def health():
    return {"ok": True}


# ============================================================
# CHECKOUT SESSION (CALLED BY TELEGRAM BOT)
# ============================================================
@app.post("/create_checkout_session")
async def create_checkout_session(request: Request):
    body = await request.json()

    # Required inputs from bot
    order_id = str(body.get("order_id", "")).strip()
    user_id = str(body.get("user_id", "")).strip()
    amount_sgd = body.get("amount", None)

    if not order_id or not user_id or amount_sgd is None:
        raise HTTPException(status_code=400, detail="Missing order_id, user_id, or amount")

    try:
        amount_cents = int(round(float(amount_sgd) * 100))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid amount")

    if amount_cents <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")

    # ✅ IMPORTANT: card only unless PayNow is fully enabled/approved on Stripe account
    payment_method_types = ["card"]

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=payment_method_types,
            line_items=[
                {
                    "price_data": {
                        "currency": "sgd",
                        "product_data": {"name": f"Order #{order_id}"},
                        "unit_amount": amount_cents,
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            # Must be HTTPS and stable (ngrok is ok for dev)
            success_url=f"{PUBLIC_BASE_URL}/payment/success?order_id={order_id}",
            cancel_url=f"{PUBLIC_BASE_URL}/payment/cancel?order_id={order_id}",
            metadata={
                "type": "escrow_payment",
                "order_id": order_id,
                "user_id": user_id,
            },
        )

        log.info(f"✅ Created Stripe Checkout Session: order={order_id} session={session.id}")

        return {"checkout_url": session.url, "session_id": session.id}

    except Exception as e:
        log.error(f"⚠️ Stripe Checkout Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 📡 STRIPE WEBHOOK HANDLER — SOURCE OF TRUTH
# ============================================================
@app.post("/webhook")
async def webhook_handler(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing stripe-signature header")

    # 🔐 Validate webhook signature
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        log.error(f"❌ Invalid Webhook Signature: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    event_type = event.get("type")
    obj = event["data"]["object"]

    log.info(f"📡 Stripe Event Received: {event_type}")

    # We care about successful payment completion
    if event_type == "checkout.session.completed":
        session = obj
        metadata = session.get("metadata", {}) or {}
        order_type = metadata.get("type")

        # ----------------------------------------------------
        # 🔒 ESCROW PAYMENT FLOW
        # ----------------------------------------------------
        if order_type == "escrow_payment":
            order_id = (metadata.get("order_id") or "").strip()
            user_id = (metadata.get("user_id") or "").strip()

            if not order_id:
                log.warning("⚠️ Missing order_id in metadata for escrow_payment")
                return {"status": "ignored"}

            orders = load_json(ORDERS_FILE)

            # ✅ orders.json should be dict keyed by order_id
            if order_id in orders and isinstance(orders[order_id], dict):
                orders[order_id]["status"] = "escrow_hold"  # move into escrow ONLY after webhook
                orders[order_id]["stripe_session_id"] = session.get("id")
                orders[order_id]["stripe_payment_intent"] = session.get("payment_intent")
                orders[order_id]["paid_by_user_id"] = user_id
                save_json(ORDERS_FILE, orders)

                log.info(f"🔒 Order moved to escrow_hold: {order_id}")
            else:
                log.warning(f"⚠️ Order not found or invalid shape: {order_id}")

        # ----------------------------------------------------
        # 💰 WALLET TOP-UP FLOW (optional)
        # ----------------------------------------------------
        if order_type == "wallet_topup":
            user_id = (metadata.get("user_id") or "").strip()
            if not user_id:
                log.warning("⚠️ Missing user_id in metadata for wallet_topup")
                return {"status": "ignored"}

            amount_total = session.get("amount_total")  # in cents
            if amount_total is None:
                log.warning("⚠️ Missing amount_total for wallet_topup")
                return {"status": "ignored"}

            amount = float(amount_total) / 100.0

            balances = load_json(BALANCE_FILE)
            current = float(balances.get(user_id, 0.0))
            balances[user_id] = round(current + amount, 2)
            save_json(BALANCE_FILE, balances)

            log.info(f"💰 Wallet Top-up +${amount:.2f} SGD → User {user_id}")

    return {"status": "success"}

#Instructions to run the server in development mode
# ============================================================
# RUN (DEV):
# 1) uvicorn server:app --reload --port 4242
# 2) ngrok http 4242
# 3) Stripe webhook endpoint (Dashboard) points to:
#       https://<your-ngrok>.ngrok-free.dev/webhook
# ============================================================
