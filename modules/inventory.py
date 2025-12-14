# Inventory Control Module
# ------------------------
# Purpose:
# - Manage stock for seller-listed products
# - Prevent overselling
# - Deduct stock after payment confirmation
#
# Design notes:
# - Works alongside existing marketplace logic
# - Does NOT replace or modify teammate code
# - Uses seller_products.json as the data source
# - Built-in catalog items are treated as unlimited stock

from typing import Optional, Tuple
from modules import storage


def _load_products():
    return storage.load_json(storage.SELLER_PRODUCTS_FILE)


def _save_products(data):
    storage.save_json(storage.SELLER_PRODUCTS_FILE, data)


def get_product(sku: str) -> Optional[dict]:
    data = _load_products()
    for _, items in data.items():
        for p in items:
            if p.get("sku") == sku:
                return p
    return None


def ensure_stock(sku: str, default: int = 10):
    data = _load_products()
    changed = False

    for _, items in data.items():
        for p in items:
            if p.get("sku") == sku and "stock" not in p:
                p["stock"] = default
                changed = True

    if changed:
        _save_products(data)


def check_stock(sku: str, qty: int) -> Tuple[bool, int]:
    product = get_product(sku)

    # Built-in catalog item
    if not product:
        return True, -1

    stock = int(product.get("stock", 0))
    return stock >= qty, stock


def deduct_stock(sku: str, qty: int) -> bool:
    data = _load_products()
    for _, items in data.items():
        for p in items:
            if p.get("sku") == sku:
                stock = int(p.get("stock", 0))
                if stock < qty:
                    return False
                p["stock"] = stock - qty
                _save_products(data)
                return True
    return True


def restore_stock(sku: str, qty: int):
    data = _load_products()
    for _, items in data.items():
        for p in items:
            if p.get("sku") == sku:
                p["stock"] = int(p.get("stock", 0)) + qty
                _save_products(data)
                return
            