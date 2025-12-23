import os
import json
import time
from typing import Dict, List
from modules import inventory

PENDING_STATUSES = {"pending", "awaiting_payment", "created"}

# =========================================================
# FILE PATHS
# =========================================================
BALANCES_FILE = "balances.json"
ORDERS_FILE = "orders.json"
ROLES_FILE = "roles.json"
SELLER_PRODUCTS_FILE = "seller_products.json"
MESSAGES_FILE = "messages.json"
WALLETS_FILE = "wallets.json"
NOTIFICATIONS_FILE = "notifications.json"
USERS_FILE = "users.json"

# =========================================================
# RUNTIME STATE (IN-MEMORY)
# =========================================================
last_message_time = {}
user_flow_state = {}
active_private_chats = {}
active_public_chat = set()


# =========================================================
# ENSURE FILES EXIST
# =========================================================
FILES_AND_DEFAULTS = {
    BALANCES_FILE: {},
    ORDERS_FILE: {},                 # 🔒 orders stored as {order_id: order}
    ROLES_FILE: {},
    SELLER_PRODUCTS_FILE: {},
    MESSAGES_FILE: {},
    WALLETS_FILE: {},
    USERS_FILE: {},
    NOTIFICATIONS_FILE: []
}

for path, default in FILES_AND_DEFAULTS.items():
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2)

# =========================================================
# JSON HELPERS
# =========================================================
def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# =========================================================
# ANTI-SPAM
# =========================================================
def is_spamming(user_id: int, cooldown: float = 1.25) -> bool:
    now = time.time()
    last = last_message_time.get(user_id, 0)
    if now - last < cooldown:
        return True
    last_message_time[user_id] = now
    return False

# =========================================================
# BALANCES
# =========================================================
def get_balance(user_id: int) -> float:
    return float(load_json(BALANCES_FILE).get(str(user_id), 0.0))

def set_balance(user_id: int, value: float):
    data = load_json(BALANCES_FILE)
    data[str(user_id)] = round(float(value), 2)
    save_json(BALANCES_FILE, data)

def update_balance(user_id: int, delta: float):
    set_balance(user_id, get_balance(user_id) + float(delta))

# =========================================================
# ORDERS (🔥 SINGLE DATA MODEL)
# =========================================================
def add_order(
    buyer_id: int,
    item_name: str,
    qty: int,
    amount: float,
    method: str,
    seller_id: int
) -> str:
    orders = load_json(ORDERS_FILE)

    order_id = f"ord_{int(time.time())}"
    orders[order_id] = {
        "id": order_id,
        "item": item_name,
        "qty": int(qty),
        "amount": float(amount),
        "method": method,
        "seller_id": seller_id,
        "buyer_id": buyer_id,
        "status": "pending",
        "ts": int(time.time()),
    }

    save_json(ORDERS_FILE, orders)
    return order_id

def get_order(order_id: str):
    return load_json(ORDERS_FILE).get(order_id)

def update_order_status(order_id: str, status: str):
    orders = load_json(ORDERS_FILE)
    if order_id in orders:
        orders[order_id]["status"] = status
        save_json(ORDERS_FILE, orders)

def get_user_orders(user_id: int) -> Dict[str, dict]:
    """
    Returns all orders where user is buyer or seller
    Output: {order_id: order}
    """
    orders = load_json(ORDERS_FILE)
    result = {}

    for oid, o in orders.items():
        if o.get("buyer_id") == user_id or o.get("seller_id") == user_id:
            result[oid] = o

    return result

def list_orders_for_user(user_id: int) -> list[dict]:
    orders = load_json(ORDERS_FILE)
    out = []

    for oid, o in orders.items():
        if o.get("buyer_id") == user_id or o.get("seller_id") == user_id:
            if is_archived_for_user(o, user_id):
                continue
            o = dict(o)
            o["id"] = oid
            out.append(o)

    return out

def get_all_disputed_orders() -> Dict[str, dict]:
    orders = load_json(ORDERS_FILE)
    disputes = {}

    for oid, o in orders.items():
        if o.get("status") == "disputed":
            disputes[oid] = o

    return disputes

# =========================================================
# ROLES
# =========================================================
def get_role(user_id: int) -> str:
    return load_json(ROLES_FILE).get(str(user_id), "buyer")

def set_role(user_id: int, role: str):
    roles = load_json(ROLES_FILE)
    roles[str(user_id)] = role
    save_json(ROLES_FILE, roles)

# =========================================================
# USERS (REGISTRY FOR USER SEARCH)
# =========================================================
def ensure_user_exists(user_id: int, username: str | None):
    users = load_json(USERS_FILE)
    uid = str(user_id)

    if uid not in users:
        users[uid] = {
            "username": (username or "").lstrip("@"),
            "role": get_role(user_id),
            "created_ts": int(time.time()),
            "last_seen_ts": int(time.time()),
        }
    else:
        users[uid]["username"] = (username or users[uid].get("username", "")).lstrip("@")
        users[uid]["role"] = get_role(user_id)
        users[uid]["last_seen_ts"] = int(time.time())

    save_json(USERS_FILE, users)


def search_users(query: str):
    q = query.lower().strip()
    users = load_json(USERS_FILE)
    results = []

    for uid, u in users.items():
        username = (u.get("username") or "").lower()
        if q in uid or (username and q in username):
            results.append({
                "user_id": int(uid),
                "username": u.get("username", "unknown"),
                "role": u.get("role", "buyer"),
            })

    return results

# =========================================================
# SELLER PRODUCTS
# =========================================================
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

# =========================================================
# CHAT THREADS
# =========================================================
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

# =========================================================
# PENDING NOTIFICATIONS
# =========================================================
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
    data.setdefault(uid, []).append(message)
    _save_pending(data)

def get_pending_notifications(user_id: int):
    return _load_pending().get(str(user_id), [])

def clear_pending_notifications(user_id: int):
    data = _load_pending()
    data.pop(str(user_id), None)
    _save_pending(data)

# -------------------------
# Pending Order Management
# -------------------------

def _order_ts(o: dict) -> int:
    try:
        return int(o.get("ts", o.get("created_ts", 0)))
    except Exception:
        return 0


def cancel_pending_order(order_id: str, actor_id: int, grace_seconds: int = 900):
    orders = load_json(ORDERS_FILE)
    if order_id not in orders:
        return False, "Order not found"

    o = orders[order_id]
    status = str(o.get("status", "")).lower()

    if status not in PENDING_STATUSES:
        return False, "Order is not pending"

    if actor_id not in (o.get("buyer_id"), o.get("seller_id")):
        return False, "Not allowed"

    ts = _order_ts(o)
    if ts and int(time.time()) - ts > grace_seconds:
        return False, "Grace period ended"

    o["status"] = "cancelled"
    o["cancel_reason"] = "cancelled_by_user"
    o["cancelled_ts"] = int(time.time())
    orders[order_id] = o
    save_json(ORDERS_FILE, orders)

    inventory.release_on_failure_or_refund(order_id, "cancelled_by_user")
    return True, "Order cancelled"


def expire_stale_pending_orders(grace_seconds: int = 900) -> int:
    now = int(time.time())
    orders = load_json(ORDERS_FILE)
    expired = 0

    for oid, o in list(orders.items()):
        status = str(o.get("status", "")).lower()
        if status not in PENDING_STATUSES:
            continue

        ts = _order_ts(o)
        if not ts or now - ts <= grace_seconds:
            continue

        o["status"] = "expired"
        o["cancel_reason"] = "grace_timeout"
        o["cancelled_ts"] = now
        orders[oid] = o
        expired += 1

        inventory.release_on_failure_or_refund(oid, "grace_timeout")

    if expired:
        save_json(ORDERS_FILE, orders)

    return expired

# ----- Order archive (per user) -----

def _arch_key(user_id: int) -> str:
    return f"archived_by_{int(user_id)}"

def is_archived_for_user(order: dict, user_id: int) -> bool:
    return bool(order.get(_arch_key(user_id), False))

def archive_order_for_user(order_id: str, user_id: int) -> tuple[bool, str]:
    orders = load_json(ORDERS_FILE)
    o = orders.get(order_id)
    if not o:
        return False, "Order not found"

    if user_id not in (o.get("buyer_id"), o.get("seller_id")):
        return False, "Not allowed"

    o[_arch_key(user_id)] = True
    o["archived_ts"] = int(time.time())
    orders[order_id] = o
    save_json(ORDERS_FILE, orders)
    return True, "Archived"

def unarchive_all_for_user(user_id: int) -> int:
    orders = load_json(ORDERS_FILE)
    key = _arch_key(user_id)
    changed = 0

    for oid, o in orders.items():
        if user_id in (o.get("buyer_id"), o.get("seller_id")) and o.get(key):
            o.pop(key, None)
            orders[oid] = o
            changed += 1

    if changed:
        save_json(ORDERS_FILE, orders)

    return changed