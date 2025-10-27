import os
import stripe
from flask import Flask, request

app = Flask(__name__)
stripe.api_key = os.getenv("sk_test_51SMVMKBZTDz6kN2ep1QGIBJXy6ewPQGNmp14CzzCgiqvyqe5hu2ia9NxzPajX8BShCmxhxkF0rhLERQSdqrAb6Rd00M1o1S1Ya")
endpoint_secret = os.getenv("whsec_t2HHLgFDqs6ss9eqJlFLlKaqBilMDrTh")

@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except stripe.error.SignatureVerificationError:
        return "Invalid signature", 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        print("✅ Payment successful for:", session["id"])
        # Here you can notify your Telegram bot that payment succeeded

    return "OK", 200

if __name__ == "__main__":
    app.run(port=4242)
