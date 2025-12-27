import os
import json
import time
from modules import inventory
from typing import List, Dict, Tuple, Set

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
last_message_time: Dict[int, float] = {}
user_flow_state: Dict[int, dict] = {}
active_private_chats: Dict[int, str] = {}
active_public_chat: Set[int] = set()


# =========================================================
# ENSURE FILES EXIST
# =========================================================
FILES_AND_DEFAULTS = {
    BALANCES_FILE: {},
    ORDERS_FILE: {},                 
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
    orders = load_json(ORDERS_FILE)
    result: Dict[str, dict] = {}

    for oid, o in orders.items():
        if o.get("buyer_id") == user_id or o.get("seller_id") == user_id:
            result[oid] = o

    return result

def list_orders_for_user(user_id: int) -> List[Dict]:
    orders = load_json(ORDERS_FILE)
    out: List[Dict] = []

    for oid, o in orders.items():
        if o.get("buyer_id") == user_id or o.get("seller_id") == user_id:
            if is_archived_for_user(o, user_id):
                continue
            obj = dict(o)
            obj["id"] = oid
            out.append(obj)

    return out

def get_all_disputed_orders() -> Dict[str, dict]:
    orders = load_json(ORDERS_FILE)
    disputes: Dict[str, dict] = {}

    for oid, o in orders.items():
        if o.get("status") == "disputed":
            disputes[oid] = o

    return disputes

def update_order_status(order_id, new_status, reason=None):
    orders = load_json(ORDERS_FILE)
    if order_id in orders:
        orders[order_id]["status"] = new_status
        if reason:
            orders[order_id]["dispute_reason"] = reason
        save_json(ORDERS_FILE, orders)
        return True
    return False

# =========================================================
# Product Visibility
# =========================================================

def toggle_product_visibility(sku: str):
    data = load_json(SELLER_PRODUCTS_FILE)
    for uid, items in data.items():
        for item in items:
            if item.get("sku") == sku:
                # Flip the boolean
                item["hidden"] = not item.get("hidden", False)
                save_json(SELLER_PRODUCTS_FILE, data)
                return True
    return False

# =========================================================
# Search for users in marketplace
# =========================================================

# modules/storage.py

def search_users(query: str, all_products: list):
    query = query.lower().strip()
    found_users = {}

    # 1. Load primary user database
    data = load_json(USERS_FILE) 
    
    if isinstance(data, dict):
        for uid, udata in data.items():
            if query == str(uid) or query in udata.get("username", "").lower():
                found_users[str(uid)] = {"user_id": uid, "username": udata.get("username", "unknown")}

    # 2. Use the passed products list to find sellers
    # This avoids the NameError and fixes the search failure in your images
    for it in all_products:
        sid = str(it.get("seller_id", ""))
        if query == sid:
            if sid not in found_users:
                found_users[sid] = {"user_id": sid, "username": "Marketplace Seller"}

    return list(found_users.values())
# =========================================================
# ROLES
# =========================================================
def get_role(user_id: int) -> str:
    return load_json(ROLES_FILE).get(str(user_id), "buyer")

def set_role(user_id: int, role: str):
    roles = load_json(ROLES_FILE)
    roles[str(user_id)] = role
    save_json(ROLES_FILE, roles)

def set_seller_status(user_id: int, status: str):
    users = load_json(USERS_FILE)
    u = users.setdefault(str(user_id), {})
    u["seller_status"] = status
    save_json(USERS_FILE, users)


def get_seller_status(user_id: int) -> str:
    if user_id == ADMIN_ID:
        return "verified"

    users = load_json(USERS_FILE)
    return users.get(str(user_id), {}).get("seller_status", "pending")



# =========================================================
# USERS
# =========================================================
def ensure_user_exists(user_id: int, username: str):
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

def search_users(query: str, all_products: list):
    query = query.lower().strip()
    found_users = {}

    # 1. Load your primary user database
    # (Using 'load_json' directly as we are inside storage.py)
    data = load_json(USERS_FILE) 
    
    if isinstance(data, dict):
        for uid, udata in data.items():
            if query == str(uid) or query in udata.get("username", "").lower():
                found_users[str(uid)] = {"user_id": uid, "username": udata.get("username", "unknown")}

    # 2. Use the passed products list to find sellers
    # This fixes the search failure for IDs like 1576365386
    for it in all_products:
        sid = str(it.get("seller_id", ""))
        if query == sid:
            if sid not in found_users:
                found_users[sid] = {"user_id": sid, "username": "Marketplace Seller"}

    return list(found_users.values())

# =========================================================
# SELLER PRODUCTS
# =========================================================
def list_seller_products(seller_id: int) -> List[Dict]:
    return load_json(SELLER_PRODUCTS_FILE).get(str(seller_id), [])

def add_seller_product(seller_id: int, title: str, price: float, desc: str) -> str:
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

def save_thread(thread_id: str, thread_data: Dict):
    threads = load_json(MESSAGES_FILE)
    threads[thread_id] = thread_data
    save_json(MESSAGES_FILE, threads)

def create_thread(buyer_id: int, seller_id: int, product: Dict) -> str:
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
# NOTIFICATIONS
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

def get_pending_notifications(user_id: int) -> List[str]:
    return _load_pending().get(str(user_id), [])

def clear_pending_notifications(user_id: int):
    data = _load_pending()
    data.pop(str(user_id), None)
    _save_pending(data)

# -------------------------
# Pending Order Management
# -------------------------

def _order_ts(o: Dict) -> int:
    try:
        return int(o.get("ts", o.get("created_ts", 0)))
    except Exception:
        return 0

def cancel_pending_order(order_id: str, actor_id: int, grace_seconds: int = 900) -> Tuple[bool, str]:
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

# ----- Order archive -----

def _arch_key(user_id: int) -> str:
    return f"archived_by_{int(user_id)}"

def is_archived_for_user(order: Dict, user_id: int) -> bool:
    return bool(order.get(_arch_key(user_id), False))

def archive_order_for_user(order_id: str, user_id: int) -> Tuple[bool, str]:
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
