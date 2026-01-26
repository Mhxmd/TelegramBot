import os
import pathlib
from time import time
from dotenv import load_dotenv
import requests
import json
import logging

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
HITPAY_API_BASE = os.getenv(
    "HITPAY_API_BASE",
    "https://api.sandbox.hit-pay.com/v1"
).strip()

if not HITPAY_API_KEY:
    raise RuntimeError("HITPAY_API_KEY missing in .env")


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
ORDERS_FILE = BASE_DIR / "data" / "orders.json"

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
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("{}")
    return json.loads(path.read_text())

def save_json(path: pathlib.Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))

# ============================================================
# ❤️ HEALTH CHECK
# ============================================================
@app.get("/health")
def health():
    return {"status": "ok", "ts": time.time()}

# ============================================================
# 🌐 PAYMENT PAGES
# ============================================================
@app.get("/payment/success", response_class=HTMLResponse)
async def payment_success(order_id: str):
    # This URL pulls from your .env PUBLIC_BASE_URL 
    # to ensure the redirect back to the bot is accurate.
    bot_link = f"https://t.me/Xchange_ShopBot?start=success_{order_id}"
    
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Payment Successful | Xchange</title>
        <meta http-equiv="refresh" content="5;url={bot_link}">
        <style>
            :root {{
                --bg: #020617;
                --card: #0f172a;
                --text: #f8fafc;
                --primary: #0088cc;
                --success: #22c55e;
            }}
            body {{
                background-color: var(--bg);
                color: var(--text);
                font-family: -apple-system, system-ui, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
            }}
            .container {{
                background: var(--card);
                padding: 40px;
                border-radius: 24px;
                box-shadow: 0 20px 50px rgba(0,0,0,0.3);
                text-align: center;
                max-width: 400px;
                width: 90%;
                border: 1px solid #1e293b;
            }}
            .checkmark {{
                width: 80px;
                height: 80px;
                background: var(--success);
                color: white;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 40px;
                margin: 0 auto 20px;
            }}
            h1 {{ margin: 0 0 10px; font-size: 24px; }}
            p {{ color: #94a3b8; line-height: 1.6; margin-bottom: 30px; }}
            .order-id {{
                display: block;
                font-family: monospace;
                background: #1e293b;
                padding: 5px;
                border-radius: 5px;
                color: #38bdf8;
                margin-top: 10px;
            }}
            .btn {{
                background: var(--primary);
                color: white;
                text-decoration: none;
                padding: 14px 28px;
                border-radius: 12px;
                font-weight: 600;
                display: block;
                transition: transform 0.2s;
            }}
            .btn:active {{ transform: scale(0.98); }}
            .loader {{
                margin-top: 20px;
                font-size: 12px;
                color: #64748b;
            }}
            .spinner {{
                width: 12px;
                height: 12px;
                border: 2px solid #334155;
                border-top: 2px solid var(--primary);
                border-radius: 50%;
                display: inline-block;
                animation: spin 1s linear infinite;
                margin-right: 5px;
            }}
            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="checkmark">✓</div>
            <h1>Payment Received</h1>
            <p>Your order is now secured in escrow.<br>
               <span class="order-id">ID: {order_id}</span>
            </p>
            
            <a href="{bot_link}" class="btn">Return to Telegram</a>
            
            <div class="loader">
                <div class="spinner"></div>
                Redirecting automatically in 5 seconds...
            </div>
        </div>
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
            f"{HITPAY_API_BASE}/payment-requests",
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
        raise HTTPException(status_code=400, detail="Missing order_id, user_id, or amount")

    try:
        # Stripe expects integers in cents
        amount_cents = int(round(float(amount) * 100))

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": "sgd",
                    "product_data": {"name": f"Xchange Order #{order_id}"},
                    "unit_amount": amount_cents,
                },
                "quantity": 1,
            }],
            success_url=f"{PUBLIC_BASE_URL}/payment/success?order_id={order_id}",
            cancel_url=f"{PUBLIC_BASE_URL}/payment/cancel?order_id={order_id}",
            metadata={
                "order_id": str(order_id),
                "user_id": str(user_id),
            },
        )
        return {"checkout_url": session.url}
    except Exception as e:
        log.error(f"Stripe Session Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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

