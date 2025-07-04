# push_dispatcher.py

import json
import os
from dotenv import load_dotenv
from pywebpush import webpush, WebPushException

# Load environment variables
load_dotenv()

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_EMAIL = os.getenv("VAPID_EMAIL")

VAPID_CLAIMS = {
    "sub": VAPID_EMAIL
}

# Load mock subscriber list (will expand later)
with open("subscribers.json", "r") as f:
    subscribers = json.load(f)

def send_push_notification(sub, message):
    try:
        webpush(
            subscription_info=sub,
            data=message,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=VAPID_CLAIMS
        )
        print(f"Push sent to: {sub['endpoint'][:50]}...")
    except WebPushException as ex:
        print(f"Failed to send push: {ex}")

# Send to all subscribers
if __name__ == "__main__":
    message = "New high-risk alert from Sentinel AI!"
    for sub in subscribers:
        send_push_notification(sub, message)
