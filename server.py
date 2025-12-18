import os
import json
import logging
import pathlib
import requests

from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
import stripe

# ============================================================
# 🔧 LOAD ENV FIRST (CRITICAL)
# ============================================================
BASE_DIR = pathlib.Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ============================================================
# 🔑 ENV VARS
# ============================================================
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip()

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()

HITPAY_API_KEY = os.getenv("HITPAY_API_KEY", "").strip()
HITPAY_BASE_URL = "https://api.hit-pay.com/v1"

# ============================================================
# ❌ HARD FAIL IF MISSING
# ============================================================
if not PUBLIC_BASE_URL:
    raise RuntimeError("PUBLIC_BASE_URL missing in .env")

if not STRIPE_SECRET_KEY:
    raise RuntimeError("STRIPE_SECRET_KEY missing in .env")

if not STRIPE_WEBHOOK_SECRET:
    raise RuntimeError("STRIPE_WEBHOOK_SECRET missing in .env")

if not HITPAY_API_KEY:
    raise RuntimeError("HITPAY_API_KEY missing in .env")

stripe.api_key = STRIPE_SECRET_KEY

# ============================================================
# 📂 FILES
# ============================================================
ORDERS_FILE = BASE_DIR / "orders.json"

# ============================================================
# 🚀 APP INIT
# ============================================================
app = FastAPI()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("server")

# ============================================================
# 🧠 JSON HELPERS
# ============================================================
def load_json(path: pathlib.Path):
    if not path.exists():
        path.write_text("{}")
    return json.loads(path.read_text())

def save_json(path: pathlib.Path, data):
    path.write_text(json.dumps(data, indent=2))

# ============================================================
# ❤️ HEALTH CHECK
# ============================================================
@app.get("/health")
async def health():
    return {"ok": True}

# ============================================================
# 🌐 PAYMENT PAGES
# ============================================================
@app.get("/payment/success", response_class=HTMLResponse)
async def payment_success(order_id: str):
    return f"""
    <html>
      <head>
        <meta http-equiv="refresh"
              content="4;url=https://t.me/Xchange_ShopBot?start=success_{order_id}">
      </head>
      <body style="background:#020617;color:white;text-align:center;padding-top:20vh">
        <h1>✅ Payment Successful</h1>
        <p>Order <b>{order_id}</b> is now in escrow.</p>
      </body>
    </html>
    """

@app.get("/payment/cancel", response_class=HTMLResponse)
async def payment_cancel(order_id: str):
    return f"""
    <html>
      <body style="background:#020617;color:white;text-align:center;padding-top:20vh">
        <h1>❌ Payment Cancelled</h1>
        <p>Order <b>{order_id}</b> was not completed.</p>
      </body>
    </html>
    """

# ============================================================
# 💸 HITPAY CREATE PAYMENT
# ============================================================
@app.post("/hitpay/create_payment")
async def hitpay_create_payment(request: Request):
    body = await request.json()

    order_id = body.get("order_id")
    amount = body.get("amount")

    if not order_id or not amount:
        raise HTTPException(status_code=400, detail="Missing order_id or amount")

    payload = {
        "amount": round(float(amount), 2),
        "currency": "SGD",
        "reference_number": order_id,
        "redirect_url": f"{PUBLIC_BASE_URL}/payment/success?order_id={order_id}",
        "webhook_url": f"{PUBLIC_BASE_URL}/hitpay/webhook",
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
        log.error(f"❌ HitPay error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================
# 💳 STRIPE CHECKOUT
# ============================================================
@app.post("/create_checkout_session")
async def create_checkout_session(request: Request):
    body = await request.json()

    order_id = body.get("order_id")
    user_id = body.get("user_id")
    amount = body.get("amount")

    if not order_id or not user_id or amount is None:
        raise HTTPException(status_code=400, detail="Missing fields")

    amount_cents = int(round(float(amount) * 100))

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

    return {"checkout_url": session.url}

# ============================================================
# 📡 STRIPE WEBHOOK
# ============================================================
@app.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")

    event = stripe.Webhook.construct_event(
        payload, sig, STRIPE_WEBHOOK_SECRET
    )

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        order_id = session["metadata"]["order_id"]

        orders = load_json(ORDERS_FILE)
        orders.setdefault(order_id, {})["status"] = "escrow_hold"
        save_json(ORDERS_FILE, orders)

    return {"status": "ok"}

# ============================================================
# 📡 HITPAY WEBHOOK
# ============================================================
@app.post("/hitpay/webhook")
async def hitpay_webhook(request: Request):
    payload = await request.json()

    status = payload.get("status")
    order_id = payload.get("reference_number")

    if status != "completed" or not order_id:
        return {"status": "ignored"}

    orders = load_json(ORDERS_FILE)
    orders.setdefault(order_id, {})["status"] = "escrow_hold"
    save_json(ORDERS_FILE, orders)

    log.info(f"🔒 Order {order_id} escrowed via HitPay")

    return {"status": "ok"}
