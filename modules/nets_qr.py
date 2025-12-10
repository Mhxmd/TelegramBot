# modules/nets_qr.py
import os, json, base64, hashlib, time
import aiohttp
from io import BytesIO
from PIL import Image
import qrcode

NETS_ENDPOINT = os.getenv("NETS_QR_ENDPOINT", "https://sandbox-nets-openapi.nets.com.sg/api/QR")
MERCHANT_ID  = os.getenv("NETS_MID")
KEY_ID       = os.getenv("NETS_KEY_ID")
SECRET_KEY   = os.getenv("NETS_SECRET_KEY")

async def generate_nets_qr(amount: float):
    """
    Request NETS QR from Sandbox API
    Returns (image_bytes, reference_code)
    """
    ref = f"NETS{int(time.time())}"
    amt_in_cents = int(amount * 100)

    payload = {
        "ss": "1",
        "msg": {
            "netsMid": MERCHANT_ID,
            "merchantTxnRef": ref,
            "txnAmount": str(amt_in_cents),
            "currencyCode": "SGD",
            "paymentType": "SALE",
            "submissionMode": "B",
            "clientType": "W"
        }
    }

    # convert to JSON string
    txnReq = json.dumps(payload, separators=(",", ":"))

    # -------------------------------------------
    # Generate MAC = Base64( SHA256(txnReq + secretKey) )
    # -------------------------------------------
    mac_raw = hashlib.sha256((txnReq + SECRET_KEY).encode()).digest()
    mac_b64 = base64.b64encode(mac_raw).decode()

    headers = {
        "Content-Type": "application/json",
        "keyId": KEY_ID,
        "hmac": mac_b64
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(NETS_ENDPOINT, data=txnReq, headers=headers) as resp:
                data = await resp.json()

                if "qrCodeData" in data.get("msg", {}):
                    qr_data = data["msg"]["qrCodeData"]

                    # Convert returned string → actual QR code image
                    img = qrcode.make(qr_data)
                    bio = BytesIO()
                    img.save(bio, format='PNG')
                    bio.seek(0)
                    return bio, ref

                else:
                    return fallback_qr(amount, ref)

    except Exception:
        return fallback_qr(amount, ref)


def fallback_qr(amount, ref):
    """Failsafe so bot doesn't crash if NETS sandbox is down"""
    img = qrcode.make(f"FAILED_SANDBOX://PAYMENT?ref={ref}&amt={amount}")
    bio = BytesIO()
    img.save(bio, "PNG")
    bio.seek(0)
    return bio, ref
