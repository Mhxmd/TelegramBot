import os
import json
import time

# File paths
BALANCES_FILE = "balances.json"
ORDERS_FILE = "orders.json"
ROLES_FILE = "roles.json"
SELLER_PRODUCTS_FILE = "seller_products.json"
MESSAGES_FILE = "messages.json"
WALLETS_FILE = "wallets.json"
NOTIFICATIONS_FILE = "notifications.json"

# In-memory runtime data
last_message_time: dict[int, float] = {}
user_flow_state: dict[int, dict] = {}
active_private_chats: dict[int, str] = {}
active_public_chat: set[int] = set()

# Ensure files exist
for path, default in [
    (BALANCES_FILE, {}),
    (ORDERS_FILE, {}),
    (ROLES_FILE, {}),
    (SELLER_PRODUCTS_FILE, {}),
    (MESSAGES_FILE, {}),
    (WALLETS_FILE, {}),
    (NOTIFICATIONS_FILE, [])
]:
    if not os.path.exists(path):
        with open(path, "w") as f:
            json.dump(default, f, indent=2)

# JSON utils
def load_json(path: str):
    with open(path, "r") as f:
        return json.load(f)

def save_json(path: str, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

# Anti-spam / cooldown
def is_spamming(user_id: int, cooldown: float = 1.25) -> bool:
    now = time.time()
    last = last_message_time.get(user_id, 0)
    if now - last < cooldown:
        return True
    last_message_time[user_id] = now
    return False

# Balances
def get_balance(user_id: int) -> float:
    return float(load_json(BALANCES_FILE).get(str(user_id), 0.0))

def set_balance(user_id: int, value: float):
    data = load_json(BALANCES_FILE)
    data[str(user_id)] = round(float(value), 2)
    save_json(BALANCES_FILE, data)

def update_balance(user_id: int, delta: float):
    set_balance(user_id, get_balance(user_id) + float(delta))

# Orders
def add_order(user_id: int, item_name: str, qty: int, amount: float, method: str, seller_id: int):
    orders = load_json(ORDERS_FILE)
    order = {
        "id": f"ord_{int(time.time())}",
        "item": item_name,
        "qty": int(qty),
        "amount": float(amount),
        "method": method,
        "seller_id": seller_id,
        "buyer_id": user_id,
        "status": "pending",
        "ts": int(time.time()),
    }
    orders[order["id"]] = order
    save_json(ORDERS_FILE, orders)
    return order["id"]

def update_order_status(order_id, status):
    orders = load_json(ORDERS_FILE)
    if order_id in orders:
        orders[order_id]["status"] = status
        save_json(ORDERS_FILE, orders)

def get_order(order_id):
    return load_json(ORDERS_FILE).get(order_id)

def list_orders_for_user(user_id: int):
    orders = load_json(ORDERS_FILE)
    return [o for o in orders.values() if o["buyer_id"] == user_id or o["seller_id"] == user_id]

# Roles
def get_role(user_id: int) -> str:
    return load_json(ROLES_FILE).get(str(user_id), "buyer")

def set_role(user_id: int, role: str):
    roles = load_json(ROLES_FILE)
    roles[str(user_id)] = role
    save_json(ROLES_FILE, roles)

# Seller Products
def list_seller_products(seller_id: int):
    return load_json(SELLER_PRODUCTS_FILE).get(str(seller_id), [])

def add_seller_product(seller_id: int, title: str, price: float, desc: str):
    data = load_json(SELLER_PRODUCTS_FILE)
    products = data.get(str(seller_id), [])
    sku = f"u{seller_id}_{int(time.time())}"
    products.append({
        "sku": sku,
        "name": title,
        "price": float(price),
        "emoji": "🛒",
        "seller_id": seller_id,
        "desc": desc,
    })
    data[str(seller_id)] = products
    save_json(SELLER_PRODUCTS_FILE, data)
    return sku

# Chats
def get_thread(thread_id: str):
    return load_json(MESSAGES_FILE).get(thread_id)

def save_thread(thread_id: str, thread_data: dict):
    threads = load_json(MESSAGES_FILE)
    threads[thread_id] = thread_data
    save_json(MESSAGES_FILE, threads)

def create_thread(buyer_id: int, seller_id: int, product: dict) -> str:
    thread_id = f"t_{int(time.time())}_{buyer_id}_{seller_id}"
    threads = load_json(MESSAGES_FILE)
    threads[thread_id] = {
        "buyer_id": buyer_id,
        "seller_id": seller_id,
        "product": {
            "sku": product.get("sku"),
            "name": product.get("name"),
            "price": product.get("price"),
        },
        "messages": []
    }
    save_json(MESSAGES_FILE, threads)
    return thread_id

def append_chat_message(thread_id: str, from_user: int, text: str):
    threads = load_json(MESSAGES_FILE)
    if thread_id not in threads:
        return
    threads[thread_id]["messages"].append({
        "from": int(from_user),
        "text": text,
        "ts": int(time.time())
    })
    save_json(MESSAGES_FILE, threads)

# --------------------------
# Pending user notifications
# --------------------------

PENDING_FILE = os.path.join(os.path.dirname(__file__), "pending_notifications.json")

def _load_pending():
    if os.path.exists(PENDING_FILE):
        try:
            with open(PENDING_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def _save_pending(data):
    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def add_pending_notification(user_id: int, message: str):
    data = _load_pending()
    uid = str(user_id)
    if uid not in data:
        data[uid] = []
    data[uid].append(message)
    _save_pending(data)

def get_pending_notifications(user_id: int):
    data = _load_pending()
    return data.get(str(user_id), [])

def clear_pending_notifications(user_id: int):
    data = _load_pending()
    if str(user_id) in data:
        data.pop(str(user_id))
        _save_pending(data)
