# inventory.py — FINAL

from __future__ import annotations
import os
import time
from typing import Any, Dict, List, Optional, Tuple
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

    def __enter__(self): self.acquire(); return self
    def __exit__(self, *_): self.release()

# -------------------------
# Helpers
# -------------------------

def _load(): return storage.load_json(storage.SELLER_PRODUCTS_FILE)
def _save(d): storage.save_json(storage.SELLER_PRODUCTS_FILE, d)

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
# Availability
# -------------------------

def get_available_stock(sku: str) -> Optional[int]:
    base, var = split_sku_variant(sku)
    data = _load()
    p = _find_product_mut(data, base)
    if not p:
        return None

    _ensure_fields(p)

    if var:
        v = _find_variant_mut(p, var)
        if not v:
            return 0
        return max(0, v["stock"] - v["reserved"])

    return max(0, p["stock"] - p["reserved"])

def check_available(sku: str, qty: int):
    qty = max(1, int(qty))
    avail = get_available_stock(sku)
    if avail is None or avail >= qty:
        return True, "ok"
    return False, f"Out of stock. Available: {avail}"

check_stock = check_available  # backward compatibility

# -------------------------
# Reservation
# -------------------------

def reserve_for_payment(order_id: str, sku: str, qty: int):
    sku = str(sku)
    qty = max(1, int(qty))
    base, var = split_sku_variant(sku)

    with FileLock(_LOCK_PATH):
        data = _load()
        p = _find_product_mut(data, base)

        if not p:
            _patch_order(order_id, {"sku": sku, "inv_reserved": False})
            return True, "ok"

        _ensure_fields(p)

        if var:
            v = _find_variant_mut(p, var)
            if not v or v["stock"] - v["reserved"] < qty:
                return False, "Out of stock"
            v["reserved"] += qty
        else:
            if p["stock"] - p["reserved"] < qty:
                return False, "Out of stock"
            p["reserved"] += qty

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

    sku = o.get("sku")
    qty = int(o.get("inv_qty", 1))
    base, var = split_sku_variant(sku)

    with FileLock(_LOCK_PATH):
        data = _load()
        p = _find_product_mut(data, base)
        if not p:
            return True, "ok"

        _ensure_fields(p)

        if var:
            v = _find_variant_mut(p, var)
            if not v or v["reserved"] < qty:
                return False, "Reservation missing"
            v["reserved"] -= qty
            v["stock"] -= qty
        else:
            if p["reserved"] < qty:
                return False, "Reservation missing"
            p["reserved"] -= qty
            p["stock"] -= qty

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
    
    # NEW SAFETY CHECK:
    # If there's no SKU, or it's a Cart purchase, skip inventory logic
    if not sku or str(sku).startswith("cart_"):
        _patch_order(order_id, {"inv_reason": "skipped_no_sku"})
        return True, "ok"

    qty = int(o.get("inv_qty", 1))
    base, var = split_sku_variant(sku)

    with FileLock(_LOCK_PATH):
        data = _load()
        p = _find_product_mut(data, base)
        if not p:
            return True, "ok"

        _ensure_fields(p)

        if var:
            v = _find_variant_mut(p, var)
            if v:
                v["reserved"] = max(0, v["reserved"] - qty)
                if o.get("inv_deducted"):
                    v["stock"] += qty
        else:
            p["reserved"] = max(0, p["reserved"] - qty)
            if o.get("inv_deducted"):
                p["stock"] += qty

        _save(data)

    _patch_order(order_id, {"inv_reserved": False, "inv_deducted": False, "inv_reason": reason})
    return True, "ok"

# -------------------------
# Variations
# -------------------------

def split_sku_variant(sku: Any):
    # Safety Check: If sku is None or not a string, return immediately
    if not sku or not isinstance(sku, str):
        return None, None
        
    if "|" in sku:
        base, var = sku.split("|", 1)
        return base.strip(), var.strip()
    return sku.strip(), None

def _find_variant_mut(p, var_id):
    for v in p.get("variations", []):
        if str(v.get("id")) == var_id:
            v.setdefault("stock", 0)
            v.setdefault("reserved", 0)
            v.setdefault("price_delta", 0)
            return v
    return None
