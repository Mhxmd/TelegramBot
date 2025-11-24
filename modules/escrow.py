from modules import storage, wallet_utils as wallet

async def seller_mark_shipped(update, context, order_id):
    storage.mark_shipped(order_id)

    await update.callback_query.edit_message_text(
        f"📦 Order {order_id} marked as SHIPPED.\n"
        f"Buyer will confirm upon receiving."
    )


async def buyer_mark_received(update, context, order_id):
    storage.buyer_confirm_received(order_id)

    # release funds to seller
    data = storage.load_json(storage.ORDERS_FILE)
    order = data[order_id]

    wallet.release_escrow(order["seller_id"], order["amount"])

    storage.update_order_status(order_id, "released")

    await update.callback_query.edit_message_text(
        f"✅ You confirmed delivery.\nFunds released to seller!"
    )


async def buyer_open_dispute(update, context, order_id):
    storage.open_dispute(order_id)
    storage.update_order_status(order_id, "dispute_opened")

    await update.callback_query.edit_message_text(
        f"⚠️ Dispute opened for Order {order_id}.\nAdmin will review."
    )
