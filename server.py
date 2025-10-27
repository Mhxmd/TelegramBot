import os
import stripe
from fastapi import FastAPI, Request
from dotenv import load_dotenv

load_dotenv()
stripe.api_key = os.getenv("sk_test_51SMVMKBZTDz6kN2ep1QGIBJXy6ewPQGNmp14CzzCgiqvyqe5hu2ia9NxzPajX8BShCmxhxkF0rhLERQSdqrAb6Rd00M1o1S1Ya")

app = FastAPI()

@app.post("/create_checkout")
async def create_checkout():
    session = stripe.checkout.Session.create(
        payment_method_types=['card', 'paynow'],  # paynow works for SG
        line_items=[{
            'price_data': {
                'currency': 'sgd',
                'product_data': {'name': 'Example Item'},
                'unit_amount': 1500,  # $15.00
            },
            'quantity': 1,
        }],
        mode='payment',
        success_url='https://example.com/success',
        cancel_url='https://example.com/cancel',
    )
    return {"checkout_url": session.url}


# ==========================
# Stripe Webhook
# ==========================

@app.post("/webhook")
async def webhook_received(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    endpoint_secret = os.getenv("sk_test_51SMVMKBZTDz6kN2ep1QGIBJXy6ewPQGNmp14CzzCgiqvyqe5hu2ia9NxzPajX8BShCmxhxkF0rhLERQSdqrAb6Rd00M1o1S1Ya")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except Exception as e:
        return {"error": str(e)}

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        print(f"✅ Payment received for {session['amount_total']/100} {session['currency'].upper()}")

    return {"status": "success"}
