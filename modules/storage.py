import os
import json
import time
from typing import List, Dict, Tuple, Set
from typing import Optional, Tuple, Dict


# Initialize the global dictionary to store user carts
CART_FILE = "data/cart.json"

def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


# =========================================================
# FILE PATHS & CONFIG
# =========================================================
BALANCES_FILE = "balances.json"
ORDERS_FILE = "data/orders.json"
ORDER_EXPIRE_SECONDS = 15 * 60
ROLES_FILE = "roles.json"
SELLER_PRODUCTS_FILE = "data/seller_products.json"
MESSAGES_FILE = "messages.json"
WALLETS_FILE = "wallets.json"
USERS_FILE = "users.json"
PENDING_FILE = "pending_notifications.json"

PENDING_STATUSES = {"pending", "awaiting_payment", "created"}
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# =========================================================
# RUNTIME STATE (IN-MEMORY)
# =========================================================
last_message_time: Dict[int, float] = {}
user_flow_state: Dict[int, dict] = {}
active_private_chats: Dict[int, str] = {}
active_public_chat: Set[int] = set()

# =========================================================
# INITIALIZATION
# =========================================================
FILES_AND_DEFAULTS = {
    BALANCES_FILE: {},
    ORDERS_FILE: {},
    ROLES_FILE: {},
    SELLER_PRODUCTS_FILE: {},
    MESSAGES_FILE: {},
    WALLETS_FILE: {},
    USERS_FILE: {},
    PENDING_FILE: {}
}

for path, default in FILES_AND_DEFAULTS.items():
    if not os.path.exists(path):
        _ensure_parent_dir(path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, indent=2)


# =========================================================
# JSON HELPERS
# =========================================================
def load_json(path: str):
    # Ensure parent folder exists
    _ensure_parent_dir(path)

    # Create file if missing
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("{}")
        return {}

    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}

def save_json(path: str, data):
    _ensure_parent_dir(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# =========================================================
# SEED BUILT-IN PRODUCTS INTO SELLER_PRODUCTS (ONCE)
# =========================================================
def seed_builtin_products_once():
    data = load_json(SELLER_PRODUCTS_FILE)
    if not isinstance(data, dict):
        data = {}

    # Already seeded
    if "0" in data and isinstance(data["0"], list) and len(data["0"]) > 0:
        return

    data["0"] = [
        {"sku": "cat", "name": "Cat Plush", "price": 15, "emoji": "🐱", "seller_id": 0, "desc": "Built-in item", "stock": 999, "reserved": 0, "hidden": False},
        {"sku": "hoodie", "name": "Hoodie", "price": 30, "emoji": "🧥", "seller_id": 0, "desc": "Built-in item", "stock": 999, "reserved": 0, "hidden": False},
        {"sku": "blackcap", "name": "Black Cap", "price": 12, "emoji": "🧢", "seller_id": 0, "desc": "Built-in item", "stock": 999, "reserved": 0, "hidden": False},
    ]
    save_json(SELLER_PRODUCTS_FILE, data)

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
    new_bal = get_balance(user_id) + float(delta)
    set_balance(user_id, max(0, new_bal))

def get_cart(user_id):
    full_db = load_json(CART_FILE)
    return full_db.get(str(user_id), {})

# =========================================================
# ORDERS & DISPUTES
# =========================================================
def add_order(buyer_id: int, item_name: str, qty: int, amount: float, method: str, seller_id: int) -> str:
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

def get_order_by_id(order_id: str):
    return load_json(ORDERS_FILE).get(str(order_id))

def update_order_status(order_id: str, new_status: str, reason: str = None) -> bool:
    orders = load_json(ORDERS_FILE)
    if order_id in orders:
        orders[order_id]["status"] = new_status
        if reason:
            orders[order_id]["status_reason"] = reason
        save_json(ORDERS_FILE, orders)
        return True
    return False

def list_orders_for_user(user_id: int) -> List[Dict]:
    orders = load_json(ORDERS_FILE)
    out: List[Dict] = []
    for oid, o in orders.items():
        if user_id in (o.get("buyer_id"), o.get("seller_id")):
            if not is_archived_for_user(o, user_id):
                obj = dict(o)
                obj["id"] = oid
                out.append(obj)
    return sorted(out, key=lambda x: x.get('ts', 0), reverse=True)

# =========================================================
# PRODUCT VISIBILITY
# =========================================================
def toggle_product_visibility(sku: str):
    data = load_json(SELLER_PRODUCTS_FILE)
    for uid, items in data.items():
        for item in items:
            if item.get("sku") == sku:
                item["hidden"] = not item.get("hidden", False)
                save_json(SELLER_PRODUCTS_FILE, data)
                return True
    return False


# =========================================================
# SELLER PRODUCTS
# =========================================================
def add_seller_product(
    seller_id: int,
    title: str,
    price: float,
    desc: str,
    stock: int = 1,
    emoji: str = "📦"
) -> str:
    data = load_json(SELLER_PRODUCTS_FILE)

    sid = str(seller_id)
    data.setdefault(sid, [])

    sku = f"sku_{seller_id}_{int(time.time())}"

    product = {
        "sku": sku,
        "name": title,
        "price": float(price),
        "desc": desc,
        "stock": int(stock),
        "emoji": emoji,
        "seller_id": seller_id,
        "hidden": False,
        "created_ts": int(time.time())
    }

    data[sid].append(product)
    save_json(SELLER_PRODUCTS_FILE, data)

    return sku

def get_seller_product_by_sku(sku: str) -> Optional[Tuple[str, Dict]]:
    data = load_json(SELLER_PRODUCTS_FILE)
    for sid, items in data.items():
        for it in items:
            if str(it.get("sku")) == str(sku):
                return sid, it
    return None, None

def update_seller_stock(sku: str, delta: int) -> bool:
    data = load_json(SELLER_PRODUCTS_FILE)
    for sid, items in data.items():
        for it in items:
            if it.get("sku") == sku:
                cur = int(it.get("stock", 0))
                nxt = cur + int(delta)
                if nxt < 0:
                    return False
                it["stock"] = nxt
                save_json(SELLER_PRODUCTS_FILE, data)
                return True
    return False


def set_seller_stock(sku: str, stock: int) -> bool:
    data = load_json(SELLER_PRODUCTS_FILE)
    for sid, items in data.items():
        for it in items:
            if it.get("sku") == sku:
                it["stock"] = max(0, int(stock))
                save_json(SELLER_PRODUCTS_FILE, data)
                return True
    return False

def list_seller_products(seller_id: int) -> List[Dict]:
    data = load_json(SELLER_PRODUCTS_FILE)
    items = data.get(str(seller_id), [])
    # return only active (not hidden) listings
    return [p for p in items if not p.get("hidden", False)]

def remove_seller_product(seller_id: int, sku: str) -> bool:
    data = load_json(SELLER_PRODUCTS_FILE)
    sid = str(seller_id)

    if sid not in data:
        return False

    items = data[sid]
    new_items = [p for p in items if p.get("sku") != sku]

    if len(new_items) == len(items):
        return False  # SKU not found

    data[sid] = new_items
    save_json(SELLER_PRODUCTS_FILE, data)
    return True

# =========================================================
# USER MANAGEMENT & SEARCH
# =========================================================
def ensure_user_exists(user_id: int, username: str):
    users = load_json(USERS_FILE)
    uid = str(user_id)
    if uid not in users:
        users[uid] = {
            "username": (username or "").lstrip("@"),
            "role": get_role(user_id),
            "created_ts": int(time.time()),
        }
    else:
        users[uid]["username"] = (username or users[uid].get("username", "")).lstrip("@")
    users[uid]["last_seen_ts"] = int(time.time())
    save_json(USERS_FILE, users)

def search_users(query: str, all_products: list):
    query = query.lower().strip()
    found_users = {}
    data = load_json(USERS_FILE)
    
    # 1. Primary DB Search
    if isinstance(data, dict):
        for uid, udata in data.items():
            if query == str(uid) or query in udata.get("username", "").lower():
                found_users[str(uid)] = {"user_id": uid, "username": udata.get("username", "unknown")}

    # 2. Seller Context Search
    for it in all_products:
        sid = str(it.get("seller_id", ""))
        if query == sid and sid not in found_users:
            found_users[sid] = {"user_id": sid, "username": "Marketplace Seller"}

    return list(found_users.values())

# =========================================================
# ROLES & SELLER STATUS
# =========================================================
def get_role(user_id: int) -> str:
    return load_json(ROLES_FILE).get(str(user_id), "buyer")

def set_role(user_id: int, role: str):
    roles = load_json(ROLES_FILE)
    roles[str(user_id)] = role
    save_json(ROLES_FILE, roles)

def get_seller_status(user_id: int) -> str:
    if user_id == ADMIN_ID: return "verified"
    users = load_json(USERS_FILE)
    return users.get(str(user_id), {}).get("seller_status", "pending")

def set_seller_status(user_id: int, status: str):
    users = load_json(USERS_FILE)
    uid = str(user_id)
    users.setdefault(uid, {})
    users[uid]["seller_status"] = status
    users[uid]["last_updated_ts"] = int(time.time())
    save_json(USERS_FILE, users)

# =========================================================
# CHAT SYSTEM
# =========================================================
def hide_chat_for_user(thread_id: str, user_id: int):
    threads = load_json(MESSAGES_FILE)
    if thread_id in threads:
        hidden = threads[thread_id].setdefault("hidden_from", [])
        if user_id not in hidden:
            hidden.append(user_id)
            save_json(MESSAGES_FILE, threads)
            return True
    return False

def append_chat_message(thread_id: str, from_user: int, text: str):
    threads = load_json(MESSAGES_FILE)
    if thread_id in threads:
        threads[thread_id]["messages"].append({
            "from": int(from_user),
            "text": text,
            "ts": int(time.time())
        })
        # If a new message comes, remove it from 'hidden' for both parties
        threads[thread_id]["hidden_from"] = []
        save_json(MESSAGES_FILE, threads)

# =========================================================
# NOTIFICATIONS
# =========================================================
def add_pending_notification(user_id: int, message: str):
    data = load_json(PENDING_FILE)
    uid = str(user_id)
    data.setdefault(uid, []).append(message)
    save_json(PENDING_FILE, data)

def get_pending_notifications(user_id: int) -> List[str]:
    return load_json(PENDING_FILE).get(str(user_id), [])

def clear_pending_notifications(user_id: int):
    data = load_json(PENDING_FILE)
    data.pop(str(user_id), None)
    save_json(PENDING_FILE, data)

# =========================================================
# ARCHIVE SYSTEM
# =========================================================
def _arch_key(user_id: int) -> str:
    return f"archived_by_{int(user_id)}"

def is_archived_for_user(order: Dict, user_id: int) -> bool:
    return bool(order.get(_arch_key(user_id), False))

def archive_order_for_user(order_id: str, user_id: int) -> Tuple[bool, str]:
    orders = load_json(ORDERS_FILE)
    o = orders.get(order_id)
    if not o: return False, "Order not found"
    o[_arch_key(user_id)] = True
    save_json(ORDERS_FILE, orders)
    return True, "Archived"

def unarchive_all_for_user(user_id: int) -> int:
    orders = load_json(ORDERS_FILE)
    key, changed = _arch_key(user_id), 0
    for oid, o in orders.items():
        if o.get(key):
            o.pop(key, None)
            changed += 1
    if changed: save_json(ORDERS_FILE, orders)
    return changed

def expire_stale_pending_orders(expire_seconds: int = ORDER_EXPIRE_SECONDS) -> int:
    """
    Marks pending orders as expired if they are older than expire_seconds.
    Returns number of orders expired.
    """
    data = load_json(ORDERS_FILE)  # use your existing load_json signature
    now = int(time.time())
    changed = 0

    # Support both dict and list storage styles
    if isinstance(data, dict):
        orders_iter = data.values()
    else:
        orders_iter = data

    for o in orders_iter:
        if not isinstance(o, dict):
            continue

        status = o.get("status")
        if status != "pending":
            continue

        created_at = o.get("ts")
        if created_at is None:
            continue

        try:
            created_at = int(created_at)
        except Exception:
            continue

        if now - created_at >= expire_seconds:
            o["status"] = "expired"
            o["expired_at"] = now
            changed += 1

    if changed:
        save_json(ORDERS_FILE, data)  # use your existing save_json

    return changed