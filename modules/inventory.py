# Inventory Control Module
# ------------------------
# Features covered:
# - Check stock before payment creation
# - Reserve stock before payment creation (prevents overselling)
# - Deduct stock only after payment confirmation (convert reservation -> deducted)
# - Restore stock on refund / failed payment (release reservation or restore deducted)
# - Race-condition safe via lock around JSON read-modify-write
#
# Storage:
# - seller_products.json fields per seller product:
#   - stock: total on hand
#   - reserved: held for pending payments
# - available = stock - reserved

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple

from modules import storage


# -------------------------
# Lock (race-safe updates)
# -------------------------

_LOCK_PATH = os.path.join(os.path.dirname(__file__), "seller_products.lock")


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
                os.write(self._fd, str(os.getpid()).encode("utf-8"))
                return
            except FileExistsError:
                if time.time() - start > self.timeout_s:
                    raise TimeoutError("Inventory lock timeout")
                time.sleep(self.retry_s)

    def release(self) -> None:
        try:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None
            if os.path.exists(self.path):
                os.remove(self.path)
        except Exception:
            pass

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()


# -------------------------
# Seller products helpers
# -------------------------

def _load_seller_products_raw() -> Dict[str, List[Dict[str, Any]]]:
    return storage.load_json(storage.SELLER_PRODUCTS_FILE)


def _save_seller_products_raw(data: Dict[str, List[Dict[str, Any]]]) -> None:
    storage.save_json(storage.SELLER_PRODUCTS_FILE, data)


def _find_seller_product_mut(data: Dict[str, List[Dict[str, Any]]], sku: str) -> Optional[Dict[str, Any]]:
    for _, items in data.items():
        for p in items:
            if str(p.get("sku")) == sku:
                return p
    return None


def _get_int(p: Dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return max(0, int(p.get(key, default)))
    except Exception:
        return default


def _ensure_fields(p: Dict[str, Any]) -> None:
    if "stock" not in p:
        p["stock"] = 0
    if "reserved" not in p:
        p["reserved"] = 0


def bootstrap_inventory_fields(default_stock: int = 10) -> None:
    """
    One-time migration helper.
    Adds missing 'stock' and 'reserved' fields to existing seller listings.
    """
    with FileLock(_LOCK_PATH):
        data = _load_seller_products_raw()
        changed = False

        for _, items in data.items():
            for p in items:
                if "stock" not in p:
                    p["stock"] = max(0, int(default_stock))
                    changed = True
                if "reserved" not in p:
                    p["reserved"] = 0
                    changed = True

        if changed:
            _save_seller_products_raw(data)


# -------------------------
# Order helpers
# -------------------------

def _get_order(order_id: str) -> Optional[Dict[str, Any]]:
    return storage.get_order(order_id)


def _save_order_patch(order_id: str, patch: Dict[str, Any]) -> bool:
    orders = storage.load_json(storage.ORDERS_FILE)
    if order_id not in orders:
        return False
    orders[order_id].update(patch)
    storage.save_json(storage.ORDERS_FILE, orders)
    return True


def ensure_order_has_sku(order_id: str, sku: str) -> bool:
    """
    Call after storage.add_order if your current add_order does not store sku.
    """
    return _save_order_patch(order_id, {"sku": sku})


# -------------------------
# Availability check
# -------------------------

def get_available_stock(sku: str) -> Optional[int]:
    """
    Returns available stock for seller products.
    Returns None for built-in / non-seller products (treat as unlimited).
    """
    data = _load_seller_products_raw()
    p = _find_seller_product_mut(data, sku)
    if not p:
        return None
    _ensure_fields(p)
    stock = _get_int(p, "stock", 0)
    reserved = _get_int(p, "reserved", 0)
    return max(0, stock - reserved)


def check_available(sku: str, qty: int) -> Tuple[bool, str]:
    """
    Check stock before payment creation.
    """
    qty = max(1, int(qty))
    avail = get_available_stock(sku)

    # Not a seller listing -> unlimited
    if avail is None:
        return True, "ok"

    if avail >= qty:
        return True, "ok"

    return False, f"Out of stock. Available: {avail}"


# -------------------------
# Inventory lifecycle
# -------------------------

def reserve_for_payment(order_id: str, sku: str, qty: int) -> Tuple[bool, str]:
    """
    Reserve stock before payment creation (prevents overselling).
    Race-safe.
    Persists reservation flags into the order.
    """
    sku = str(sku).strip()
    qty = max(1, int(qty))

    # Built-in items -> skip reservation
    preview = _load_seller_products_raw()
    if _find_seller_product_mut(preview, sku) is None:
        _save_order_patch(order_id, {"sku": sku, "inv_qty": qty, "inv_reserved": False, "inv_deducted": False})
        return True, "ok"

    with FileLock(_LOCK_PATH):
        data = _load_seller_products_raw()
        p = _find_seller_product_mut(data, sku)
        if not p:
            _save_order_patch(order_id, {"sku": sku, "inv_qty": qty, "inv_reserved": False, "inv_deducted": False})
            return True, "ok"

        _ensure_fields(p)
        stock = _get_int(p, "stock", 0)
        reserved = _get_int(p, "reserved", 0)
        available = max(0, stock - reserved)

        if available < qty:
            return False, f"Out of stock. Available: {available}"

        p["reserved"] = reserved + qty
        _save_seller_products_raw(data)

    _save_order_patch(order_id, {"sku": sku, "inv_qty": qty, "inv_reserved": True, "inv_deducted": False})
    return True, "ok"


def confirm_payment(order_id: str) -> Tuple[bool, str]:
    """
    Deduct stock only after payment confirmation.
    Converts reservation -> deducted.
    """
    o = _get_order(order_id)
    if not o:
        return False, "Order not found"

    sku = str(o.get("sku") or "").strip()
    qty = max(1, int(o.get("inv_qty") or o.get("qty") or 1))

    # Built-in items -> skip
    preview = _load_seller_products_raw()
    if _find_seller_product_mut(preview, sku) is None:
        _save_order_patch(order_id, {"inv_reserved": False, "inv_deducted": False})
        return True, "ok"

    with FileLock(_LOCK_PATH):
        data = _load_seller_products_raw()
        p = _find_seller_product_mut(data, sku)
        if not p:
            _save_order_patch(order_id, {"inv_reserved": False, "inv_deducted": False})
            return True, "ok"

        _ensure_fields(p)
        stock = _get_int(p, "stock", 0)
        reserved = _get_int(p, "reserved", 0)

        if reserved < qty:
            available_now = max(0, stock - reserved)
            return False, f"Reservation missing. Available now: {available_now}"

        if stock < qty:
            return False, f"Stock inconsistent. Stock: {stock}, need: {qty}"

        p["reserved"] = max(0, reserved - qty)
        p["stock"] = max(0, stock - qty)
        _save_seller_products_raw(data)

    _save_order_patch(order_id, {"inv_reserved": False, "inv_deducted": True})
    return True, "ok"


def release_on_failure_or_refund(order_id: str, reason: str = "failed") -> Tuple[bool, str]:
    """
    Restore stock on refund / failed payment.
    If reserved: reserved -= qty
    If deducted: stock += qty
    """
    o = _get_order(order_id)
    if not o:
        return False, "Order not found"

    sku = str(o.get("sku") or "").strip()
    qty = max(1, int(o.get("inv_qty") or o.get("qty") or 1))
    was_reserved = bool(o.get("inv_reserved", False))
    was_deducted = bool(o.get("inv_deducted", False))

    # Built-in items -> skip
    preview = _load_seller_products_raw()
    if _find_seller_product_mut(preview, sku) is None:
        _save_order_patch(order_id, {"inv_reserved": False, "inv_deducted": False, "inv_reason": reason})
        return True, "ok"

    with FileLock(_LOCK_PATH):
        data = _load_seller_products_raw()
        p = _find_seller_product_mut(data, sku)
        if not p:
            _save_order_patch(order_id, {"inv_reserved": False, "inv_deducted": False, "inv_reason": reason})
            return True, "ok"

        _ensure_fields(p)
        stock = _get_int(p, "stock", 0)
        reserved = _get_int(p, "reserved", 0)

        if was_reserved and reserved >= qty:
            p["reserved"] = max(0, reserved - qty)

        if was_deducted:
            p["stock"] = max(0, stock + qty)

        _save_seller_products_raw(data)

    _save_order_patch(order_id, {"inv_reserved": False, "inv_deducted": False, "inv_reason": reason})
    return True, "ok"            

def check_stock(sku: str, qty: int):
    """
    Backward-compatible wrapper.
    Some modules still call inventory.check_stock().
    """
    return check_available(sku, qty)