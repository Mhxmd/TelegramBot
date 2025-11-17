# modules/payments.py
# Centralized PayNow QR + Stripe helpers (Test Mode)

import qrcode
from io import BytesIO
from urllib.parse import urlencode
import time, random

# This is your fake test gateway for now
VERCEL_PAY_URL = "https://fake-paynow-yourname.vercel.app"


def generate_dummy_payment_url(order_id: str, item_name: str, amount: float) -> str:
    qs = urlencode({
        "order": order_id,
        "item": item_name,
        "amount": f"{amount:.2f}"
    })
    return VERCEL_PAY_URL.rstrip("/") + "/?" + qs


def generate_paynow_qr(amount: float, item_name: str, order_id: str = None) -> BytesIO:
    """
    Generates a *test mode* PayNow QR.
    We'll replace with real UEN-based QR later.
    """
    if order_id is None:
        order_id = f"O{int(time.time())}{random.randint(100,999)}"

    # The QR links to a fake Vercel-hosted page for demo mode
    url = generate_dummy_payment_url(order_id, item_name, amount)

    img = qrcode.make(url)
    bio = BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)

    # Attach attributes so UI can read them
    bio.order_id = order_id
    bio.url = url

    return bio
