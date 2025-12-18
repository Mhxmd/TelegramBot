import os
import json
import logging
import pathlib

import requests

import requests

HITPAY_API_KEY = os.getenv("HITPAY_API_KEY", "").strip()
HITPAY_BASE_URL = os.getenv("HITPAY_BASE_URL", "https://api.hit-pay.com/v1").strip()

if not HITPAY_API_KEY:
    raise RuntimeError("HITPAY_API_KEY missing in .env")



import stripe
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv

# ============================================================
# 🔧 LOAD ENV + CONFIG
# ============================================================
BASE_DIR = pathlib.Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip()  # ngrok https URL

if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY missing in .env")
if not STRIPE_WEBHOOK_SECRET:
    raise RuntimeError("STRIPE_WEBHOOK_SECRET missing in .env")
if not PUBLIC_BASE_URL:
    raise RuntimeError("PUBLIC_BASE_URL missing in .env")

stripe.api_key = STRIPE_SECRET_KEY

ORDERS_FILE = BASE_DIR / "orders.json"
BALANCE_FILE = BASE_DIR / "balances.json"

# ============================================================
# 🚀 APP INIT
# ============================================================
app = FastAPI()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("server")

# ============================================================
# JSON HELPERS
# ============================================================
def load_json(path: pathlib.Path):
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
# 🌐 PAYMENT LANDING PAGES
# ============================================================
@app.get("/payment/success", response_class=HTMLResponse)
async def payment_success(order_id: str):
    return f"""
    <html>
      <head>
        <meta charset="utf-8"/>
        <title>Payment Successful</title>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <meta http-equiv="refresh"
              content="5;url=https://t.me/Xchange_ShopBot?start=success_{order_id}">
        <style>
          body {{
            background:#020617;
            color:#e5e7eb;
            font-family:system-ui,-apple-system,BlinkMacSystemFont,sans-serif;
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
          h1 {{ color:#22c55e; }}
          p {{ color:#cbd5f5; }}
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

@app.get("/payment/cancel", response_class=HTMLResponse)
async def payment_cancel(order_id: str):
    return f"""
    <html>
      <head>
        <meta charset="utf-8"/>
        <title>Payment Cancelled</title>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <style>
          body {{
            background:#020617;
            color:#e5e7eb;
            font-family:system-ui,-apple-system,BlinkMacSystemFont,sans-serif;
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
          h1 {{ color:#ef4444; }}
          p {{ color:#cbd5f5; }}
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
          <p>Order <b>{order_id}</b> was not completed.</p>

          <a href="https://t.me/Xchange_ShopBot?start=cancel_{order_id}">
            ⬅ Return to Xchange Bot
          </a>
        </div>
      </body>
    </html>
    """

#Create Payment Endpoint

@app.post("/hitpay/create_payment")
async def hitpay_create_payment(request: Request):
    body = await request.json()

    order_id = body.get("order_id")
    user_id = body.get("user_id")
    amount = body.get("amount")

    if not order_id or not amount:
        raise HTTPException(status_code=400, detail="Missing order_id or amount")

    payload = {
        "amount": round(float(amount), 2),
        "currency": "SGD",
        "reference_number": order_id,
        "redirect_url": f"{PUBLIC_BASE_URL}/payment/success?order_id={order_id}",
        "webhook": f"{PUBLIC_BASE_URL}/hitpay/webhook",
        "purpose": f"Order {order_id}",
    }

    headers = {
        "X-BUSINESS-API-KEY": HITPAY_API_KEY,
        "Content-Type": "application/json",
    }

    try:
        r = requests.post(
            f"{HITPAY_BASE_URL}/payment-requests",
            json=payload,
            headers=headers,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()

        log.info(f"✅ HitPay payment created: {data['id']}")

        return {
            "checkout_url": data["url"],
            "hitpay_id": data["id"],
        }

    except Exception as e:
        log.error(f"❌ HitPay create error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 💳 CREATE STRIPE CHECKOUT SESSION
# ============================================================
@app.post("/create_checkout_session")
async def create_checkout_session(request: Request):
    body = await request.json()

    order_id = str(body.get("order_id", "")).strip()
    user_id = str(body.get("user_id", "")).strip()
    amount_sgd = body.get("amount")

    if not order_id or not user_id or amount_sgd is None:
        raise HTTPException(status_code=400, detail="Missing order_id, user_id, or amount")

    try:
        amount_cents = int(round(float(amount_sgd) * 100))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid amount")

    if amount_cents <= 0:
        raise HTTPException(status_code=400, detail="Amount must be > 0")

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": "sgd",
                    "product_data": {"name": f"Order #{order_id}"},
                    "unit_amount": amount_cents,
                },
                "quantity": 1,
            }],
            success_url=f"{PUBLIC_BASE_URL}/payment/success?order_id={order_id}",
            cancel_url=f"{PUBLIC_BASE_URL}/payment/cancel?order_id={order_id}",
            metadata={
                "type": "escrow_payment",
                "order_id": order_id,
                "user_id": user_id,
            },
        )

        log.info(f"✅ Stripe session created: {session.id}")
        return {"checkout_url": session.url, "session_id": session.id}

    except Exception as e:
        log.error(f"❌ Stripe error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# 📡 STRIPE WEBHOOK — SOURCE OF TRUTH
# ============================================================
@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing stripe-signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except Exception as e:
        log.error(f"❌ Invalid webhook signature: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    log.info(f"📡 Stripe Event: {event['type']}")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata", {}) or {}

        if metadata.get("type") == "escrow_payment":
            order_id = metadata.get("order_id")
            user_id = metadata.get("user_id")

            orders = load_json(ORDERS_FILE)

            if order_id in orders:
                orders[order_id]["status"] = "escrow_hold"
                orders[order_id]["stripe_session_id"] = session.get("id")
                orders[order_id]["stripe_payment_intent"] = session.get("payment_intent")
                orders[order_id]["paid_by_user_id"] = user_id
                save_json(ORDERS_FILE, orders)

                log.info(f"🔒 Order {order_id} moved to escrow_hold")
            else:
                log.warning(f"⚠️ Order not found: {order_id}")

    return {"status": "ok"}

@app.post("/hitpay/webhook")
async def hitpay_webhook(request: Request):
    payload = await request.json()

    # HitPay sends status updates
    status = payload.get("status")
    order_id = payload.get("reference_number")

    log.info(f"📡 HitPay webhook: {status} for {order_id}")

    if status != "completed" or not order_id:
        return {"status": "ignored"}

    orders = load_json(ORDERS_FILE)

    if order_id in orders:
        orders[order_id]["status"] = "escrow_hold"
        orders[order_id]["hitpay_payment_id"] = payload.get("id")
        save_json(ORDERS_FILE, orders)

        log.info(f"🔒 Order {order_id} moved to escrow_hold (HitPay)")
    else:
        log.warning(f"⚠️ Order not found for HitPay webhook: {order_id}")

    return {"status": "ok"}

