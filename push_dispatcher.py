# push_dispatcher.py

import json
import os
from dotenv import load_dotenv
from pywebpush import webpush, WebPushException

# Load environment variables
load_dotenv()

# VAPID credentials
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_EMAIL = os.getenv("VAPID_EMAIL")

VAPID_CLAIMS = {"sub": VAPID_EMAIL}

SUBSCRIBERS_FILE = "subscribers.json"

def load_subscribers():
    if not os.path.exists(SUBSCRIBERS_FILE):
        print("❌ subscribers.json not found.")
        return []

    try:
        with open(SUBSCRIBERS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Failed to load subscribers: {e}")
        return []

def send_push_notification(sub, message):
    try:
        webpush(
            subscription_info=sub,
            data=message,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=VAPID_CLAIMS
        )
        print(f"✅ Push sent to {sub.get('endpoint', '')[:50]}...")
    except WebPushException as ex:
        print(f"❌ Push failed [{sub.get('endpoint', '')[:50]}]: {ex}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

def send_all_push_notifications(message="🚨 New alert from Sentinel AI. Check your dashboard."):
    subscribers = load_subscribers()
    if not subscribers:
        print("⚠️ No active subscribers.")
        return

    print(f"📣 Sending push to {len(subscribers)} subscribers...")
    for sub in subscribers:
        send_push_notification(sub, message)

if __name__ == "__main__":
    send_all_push_notifications()
