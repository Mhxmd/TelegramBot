# modules/db/__init__.py

# Expose the DB pool + init functions from database.py
from .database import pool, init_db

# USERS
from .users import (
    get_or_create_user,
    get_user_by_telegram_id,
    get_user_by_id,
)

# WALLET
from .wallet import (
    get_or_create_wallet,
)

# CATEGORY
from .category import (
    get_all_categories,
)

# PRODUCTS
from .products import (
    get_product_by_id,
    count_products_by_category,
    get_products_by_category_paginated,
)

# CART + ORDERS
from .orders import (
    cart_add_item,
    create_single_product_order,
    create_order_from_cart,
    count_orders_by_buyer,
    get_orders_by_buyer_paginated,
    get_order_by_id,
)
