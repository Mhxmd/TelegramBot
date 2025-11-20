from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_product_photo_card(product: dict, page: int, total_pages: int):
    pid = product["product_id"]
    title = product["title"]
    desc = product["description"]
    price = float(product["price"])
    stock = product["stock_quantity"]
    category = product["category_name"]

    image_url = (
        product.get("image_url")
        or product.get("main_image")
        or (product["images"][0] if product.get("images") else None)
    )

    caption = (
        f"🧺 *{title}*\n"
        f"💵 Price: *${price:.2f}*\n"
        f"📦 Stock: `{stock}`\n\n"
        f"{desc}\n\n"
        f"Page {page}/{total_pages}"
    )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ Prev", callback_data=f"v2:shop:page:{category}:{page - 1}"),
            InlineKeyboardButton("➡️ Next", callback_data=f"v2:shop:page:{category}:{page + 1}")
        ],
        [InlineKeyboardButton("🛒 Add to Cart", callback_data=f"v2:cart:add:{pid}:1")],
        [InlineKeyboardButton("🔙 Categories", callback_data="v2:shop:categories")],
        [InlineKeyboardButton("🏠 Menu", callback_data="v2:menu:main")],
    ])

    return {
        "photo_url": image_url,
        "caption": caption,
        "reply_markup": kb
    }
