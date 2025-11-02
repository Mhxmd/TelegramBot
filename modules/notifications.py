from modules import storage
import time

def add_notification(user_id: int, text: str):
    notifs = storage.load_json(storage.NOTIFICATIONS_FILE)
    # notifs is a list
    notifs.append({
        "user_id": int(user_id),
        "text": text,
        "ts": int(time.time())
    })
    storage.save_json(storage.NOTIFICATIONS_FILE, notifs)
