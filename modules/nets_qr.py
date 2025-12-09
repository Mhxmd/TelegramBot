import os, time, random, aiohttp
from dotenv import load_dotenv

load_dotenv()

NETS_API_KEY     = os.getenv("NETS_API_KEY", "")
NETS_PROJECT_ID  = os.getenv("NETS_PROJECT_ID", "")
NETS_ENDPOINT    = "https://sandbox-nets-openapi.nets.com.sg/api/v1/common/payments/nets-qr/request"

async def generate_nets_qr(amount):
    txn_id = f"NETS{int(time.time())}{random.randint(100,999)}"
    
    payload = {
        "txn_id": txn_id,
        "amt_in_dollars": f"{amount:.2f}",
        "notify_mobile": 0
    }

    headers = {
        "api-key": NETS_API_KEY,
        "project-id": NETS_PROJECT_ID,
        "Content-Type": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(NETS_ENDPOINT, json=payload, headers=headers) as resp:
            data = await resp.json()
            qr_url = data["result"]["data"]["qr_url"]
            ref = data["result"]["data"]["txn_retrieval_ref"]
            return qr_url, ref