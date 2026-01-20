# inventory.py — FINAL (UPDATED)

from __future__ import annotations
import os
import time
from typing import Any, Optional
from modules import storage

_LOCK_PATH = os.path.join(os.path.dirname(__file__), "seller_products.lock")

# -------------------------
# File lock
# -------------------------

class FileLock:
    def __init__(self, path: str, timeout_s: float = 3.0, retry_s: float = 0.05):
        self.path = path
        self.timeout_s = timeout_s
        self.retry_s = retry_s
        self._fd: Optional[int] = None

    def acquire(self) -> None:
        start = time.time()
        while True:
            try:
                self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                os.write(self._fd, str(os.getpid()).encode())
                return
            except FileExistsError:
                if time.time() - start > self.timeout_s:
                    raise TimeoutError("Inventory lock timeout")
                time.sleep(self.retry_s)

    def release(self) -> None:
        try:
            if self._fd:
                os.close(self._fd)
                self._fd = None
            if os.path.exists(self.path):
                os.remove(self.path)
        except Exception:
            pass

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()

# -------------------------
# Helpers
# -------------------------

def _load():
    return storage.load_json(storage.SELLER_PRODUCTS_FILE)

def _save(d):
    storage.save_json(storage.SELLER_PRODUCTS_FILE, d)

def _find_product_mut(data, sku):
    for items in data.values():
        for p in items:
            if str(p.get("sku")) == sku:
                return p
    return None

def _ensure_fields(p):
    p.setdefault("stock", 0)
    p.setdefault("reserved", 0)

def _get_order(order_id):
    orders = storage.load_json(storage.ORDERS_FILE)
    return orders.get(order_id)

def _patch_order(order_id, patch):
    orders = storage.load_json(storage.ORDERS_FILE)
    if order_id not in orders:
        return False
    orders[order_id].update(patch)
    storage.save_json(storage.ORDERS_FILE, orders)
    return True

# -------------------------
# Variations
# -------------------------

def split_sku_variant(sku: Any):
    # Always return a string base (never None)
    if sku is None:
        return "", None

    if not isinstance(sku, str):
        sku = str(sku)

    sku = sku.strip()
    if not sku or sku.lower() == "none":
        return "", None

    if "|" in sku:
        base, var = sku.split("|", 1)
        return base.strip(), var.strip()
    return sku, None

def _find_variant_mut(p, var_id):
    for v in p.get("variations", []):
        if str(v.get("id")) == str(var_id):
            v.setdefault("stock", 0)
            v.setdefault("reserved", 0)
            v.setdefault("price_delta", 0)
            return v
    return None

# -------------------------
# Availability
# -------------------------

def get_available_stock(sku: str) -> Optional[int]:
    base, var = split_sku_variant(sku)
    if not base:
        return None

    data = _load()
    p = _find_product_mut(data, base)
    if not p:
        return None

    _ensure_fields(p)

    if var:
        v = _find_variant_mut(p, var)
        if not v:
            return 0
        return max(0, int(v["stock"]) - int(v["reserved"]))

    return max(0, int(p["stock"]) - int(p["reserved"]))

def check_available(sku: str, qty: int):
    # Contract: returns (bool, int)
    qty = max(1, int(qty))
    avail = get_available_stock(sku)

    if avail is None:
        return False, 0

    if avail >= qty:
        return True, int(avail)

    return False, int(avail)

check_stock = check_available  # backward compatibility

# -------------------------
# Reservation
# -------------------------

def reserve_for_payment(order_id: str, sku: str, qty: int):
    sku = str(sku).strip()
    qty = max(1, int(qty))

    # Hard guard
    if not sku or sku.lower() == "none":
        _patch_order(order_id, {"sku": sku, "inv_reserved": False})
        return False, "Invalid SKU"

    base, var = split_sku_variant(sku)
    if not base:
        _patch_order(order_id, {"sku": sku, "inv_reserved": False})
        return False, "Invalid SKU"
    
    o = _get_order(order_id)
    if o and o.get("inv_reserved"):
        return True, "ok"

    with FileLock(_LOCK_PATH):
        data = _load()
        p = _find_product_mut(data, base)

        # Missing product should fail, not succeed
        if not p:
            _patch_order(order_id, {"sku": sku, "inv_reserved": False})
            return False, "Product not found"

        _ensure_fields(p)

        if var:
            v = _find_variant_mut(p, var)
            if (not v) or (int(v["stock"]) - int(v["reserved"]) < qty):
                return False, "Out of stock"
            v["reserved"] = int(v["reserved"]) + qty
        else:
            if int(p["stock"]) - int(p["reserved"]) < qty:
                return False, "Out of stock"
            p["reserved"] = int(p["reserved"]) + qty

        _save(data)

    if not _patch_order(order_id, {
        "sku": sku,
        "inv_qty": qty,
        "inv_reserved": True,
        "inv_deducted": False,
    }):
        return False, "Order missing"

    return True, "ok"

# -------------------------
# Confirm payment
# -------------------------        
def confirm_payment(order_id: str):
    o = _get_order(order_id)
    if not o:
        return False, "Order not found"
    if o.get("inv_deducted"):
        return True, "ok"

    sku = o.get("sku")

    # Hard guard
    if not sku or str(sku).strip().lower() == "none":
        return False, "Invalid SKU"

    qty = int(o.get("inv_qty", 1))
    base, var = split_sku_variant(sku)
    if not base:
        return False, "Invalid SKU"

    with FileLock(_LOCK_PATH):
        data = _load()
        p = _find_product_mut(data, base)
        if not p:
            return False, "Product not found"

        _ensure_fields(p)

        if var:
            v = _find_variant_mut(p, var)
            if not v or int(v["reserved"]) < qty:
                return False, "Reservation missing"
            v_reserved = int(v["reserved"])
            v_stock = int(v["stock"])
            if v_reserved < qty or v_stock < qty:
                return False, "Insufficient stock"
            v["reserved"] = v_reserved - qty
            v["stock"] = v_stock - qty
            
        else:
            if int(p["reserved"]) < qty:
                return False, "Reservation missing"
            p_reserved = int(p["reserved"])
            p_stock = int(p["stock"])
            if p_reserved < qty or p_stock < qty:
                return False, "Insufficient stock"
            p["reserved"] = p_reserved - qty
            p["stock"] = p_stock - qty

        _save(data)

    _patch_order(order_id, {"inv_reserved": False, "inv_deducted": True})
    return True, "ok"

# -------------------------
# Rollback
# -------------------------

def release_on_failure_or_refund(order_id: str, reason="failed"):
    o = _get_order(order_id)
    if not o:
        return False, "Order not found"

    sku = o.get("sku")

    # If there's no SKU, or it's a Cart purchase, skip inventory logic
    sku_str = str(sku).strip()
    if (not sku_str) or (sku_str.lower() == "cart") or sku_str.startswith("cart_"):
        _patch_order(order_id, {"inv_reason": "skipped_cart_or_no_sku"})
        return True, "ok"

    qty = int(o.get("inv_qty", 1))
    base, var = split_sku_variant(sku)
    if not base:
        _patch_order(order_id, {"inv_reason": "skipped_invalid_sku"})
        return True, "ok"

    with FileLock(_LOCK_PATH):
        data = _load()
        p = _find_product_mut(data, base)
        if not p:
            return True, "ok"

        _ensure_fields(p)

        if var:
            v = _find_variant_mut(p, var)
            if v:
                v["reserved"] = max(0, int(v["reserved"]) - qty)
                if o.get("inv_deducted"):
                    v["stock"] = int(v["stock"]) + qty
        else:
            p["reserved"] = max(0, int(p["reserved"]) - qty)
            if o.get("inv_deducted"):
                p["stock"] = int(p["stock"]) + qty

        _save(data)

    _patch_order(order_id, {"inv_reserved": False, "inv_deducted": False, "inv_reason": reason})
    return True, "ok"

def reserve_cart_for_payment(order_id: str, items: list[dict]):
    """
    items: [{"sku": "cat", "qty": 2}, ...]
    Reserves stock for ALL items atomically.
    """
    if not items or not isinstance(items, list):
        _patch_order(order_id, {"inv_reserved": False, "inv_reason": "empty_cart"})
        return False, "Cart is empty"

    # Normalize and validate
    norm_items = []
    for it in items:
        sku = str(it.get("sku", "")).strip()
        qty = int(it.get("qty", 1) or 1)
        qty = max(1, qty)
        if not sku or sku.lower() == "none" or sku.lower() == "cart":
            return False, "Invalid cart item SKU"
        norm_items.append({"sku": sku, "qty": qty})

    o = _get_order(order_id)
    if o and o.get("inv_reserved") and o.get("inv_mode") == "cart":
        return True, "ok"

    with FileLock(_LOCK_PATH):
        data = _load()

        # 1) Check all availability first
        for it in norm_items:
            base, var = split_sku_variant(it["sku"])
            if not base:
                return False, f"Invalid SKU: {it['sku']}"

            p = _find_product_mut(data, base)
            if not p:
                return False, f"Product not found: {base}"

            _ensure_fields(p)

            if var:
                v = _find_variant_mut(p, var)
                if not v:
                    return False, f"Variant not found: {it['sku']}"
                avail = int(v["stock"]) - int(v["reserved"])
                if avail < it["qty"]:
                    return False, f"Out of stock: {it['sku']} (left {max(0, avail)})"
            else:
                avail = int(p["stock"]) - int(p["reserved"])
                if avail < it["qty"]:
                    return False, f"Out of stock: {base} (left {max(0, avail)})"

        # 2) Reserve all
        for it in norm_items:
            base, var = split_sku_variant(it["sku"])
            p = _find_product_mut(data, base)
            _ensure_fields(p)

            if var:
                v = _find_variant_mut(p, var)
                v["reserved"] = int(v["reserved"]) + it["qty"]
            else:
                p["reserved"] = int(p["reserved"]) + it["qty"]

        _save(data)

    ok = _patch_order(order_id, {
        "inv_mode": "cart",
        "inv_items": norm_items,
        "inv_reserved": True,
        "inv_deducted": False,
    })
    if not ok:
        return False, "Order missing"

    return True, "ok"


def confirm_cart_payment(order_id: str):
    """
    Deducts stock for a reserved cart order.
    """
    o = _get_order(order_id)
    if not o:
        return False, "Order not found"
    if o.get("inv_deducted") and o.get("inv_mode") == "cart":
        return True, "ok"

    items = o.get("inv_items") or []
    if o.get("inv_mode") != "cart" or not items:
        return False, "Order has no cart items"

    with FileLock(_LOCK_PATH):
        data = _load()

        # Validate reservations exist
        for it in items:
            sku = str(it.get("sku", "")).strip()
            qty = int(it.get("qty", 1) or 1)
            qty = max(1, qty)

            base, var = split_sku_variant(sku)
            if not base:
                return False, f"Invalid SKU: {sku}"

            p = _find_product_mut(data, base)
            if not p:
                return False, f"Product not found: {base}"
            _ensure_fields(p)

            if var:
                v = _find_variant_mut(p, var)
                if not v or int(v["reserved"]) < qty:
                    return False, f"Reservation missing: {sku}"
                if int(v["stock"]) < qty:
                    return False, f"Insufficient stock: {sku}"
            else:
                if int(p["reserved"]) < qty:
                    return False, f"Reservation missing: {base}"
                if int(p["stock"]) < qty:
                    return False, f"Insufficient stock: {base}"

        # Deduct
        for it in items:
            sku = str(it.get("sku", "")).strip()
            qty = int(it.get("qty", 1) or 1)
            qty = max(1, qty)

            base, var = split_sku_variant(sku)
            p = _find_product_mut(data, base)
            _ensure_fields(p)

            if var:
                v = _find_variant_mut(p, var)
                v["reserved"] = int(v["reserved"]) - qty
                v["stock"] = int(v["stock"]) - qty
            else:
                p["reserved"] = int(p["reserved"]) - qty
                p["stock"] = int(p["stock"]) - qty

        _save(data)

    _patch_order(order_id, {"inv_reserved": False, "inv_deducted": True})
    return True, "ok"


def release_cart_on_failure_or_refund(order_id: str, reason: str = "failed"):
    """
    Releases reserved stock for a cart order.
    If already deducted, adds stock back.
    """
    o = _get_order(order_id)
    if not o:
        return False, "Order not found"

    if o.get("inv_mode") != "cart":
        return False, "Not a cart order"

    items = o.get("inv_items") or []
    if not items:
        _patch_order(order_id, {"inv_reason": "empty_cart_items"})
        return True, "ok"

    with FileLock(_LOCK_PATH):
        data = _load()

        for it in items:
            sku = str(it.get("sku", "")).strip()
            qty = int(it.get("qty", 1) or 1)
            qty = max(1, qty)

            base, var = split_sku_variant(sku)
            if not base:
                continue

            p = _find_product_mut(data, base)
            if not p:
                continue
            _ensure_fields(p)

            if var:
                v = _find_variant_mut(p, var)
                if not v:
                    continue
                v["reserved"] = max(0, int(v["reserved"]) - qty)
                if o.get("inv_deducted"):
                    v["stock"] = int(v["stock"]) + qty
            else:
                p["reserved"] = max(0, int(p["reserved"]) - qty)
                if o.get("inv_deducted"):
                    p["stock"] = int(p["stock"]) + qty

        _save(data)

    _patch_order(order_id, {"inv_reserved": False, "inv_deducted": False, "inv_reason": reason})
    return True, "ok"

