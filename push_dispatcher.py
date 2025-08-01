import json
import os
from pathlib import Path
from dotenv import load_dotenv
from pywebpush import webpush, WebPushException
import logging

# --- Logging configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# VAPID credentials
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY")
VAPID_EMAIL = os.getenv("VAPID_EMAIL")

if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY or not VAPID_EMAIL:
    log.warning("Some VAPID environment variables are missing! Check Railway service variables.")

RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
if RAILWAY_ENV:
    log.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    log.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

VAPID_CLAIMS = {"sub": VAPID_EMAIL}

SUBSCRIBERS_FILE = Path("subscribers.json")

def load_subscribers():
    if not SUBSCRIBERS_FILE.exists():
        log.error("subscribers.json not found.")
        return []

    try:
        with SUBSCRIBERS_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error(f"Failed to load subscribers: {e}")
        return []

def send_push_notification(sub, message):
    try:
        webpush(
            subscription_info=sub,
            data=message,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=VAPID_CLAIMS
        )
        log.info(f"Push sent to {sub.get('endpoint', '')[:50]}...")
        return {"status": "sent", "endpoint": sub.get('endpoint', '')}
    except WebPushException as ex:
        log.error(f"Push failed [{sub.get('endpoint', '')[:50]}]: {ex}")
        return {"status": "error", "endpoint": sub.get('endpoint', ''), "reason": str(ex)}
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        return {"status": "error", "endpoint": sub.get('endpoint', ''), "reason": str(e)}

def send_all_push_notifications(message="🚨 New alert from Sentinel AI. Check your dashboard."):
    subscribers = load_subscribers()
    if not subscribers:
        log.warning("No active subscribers.")
        return

    log.info(f"Sending push to {len(subscribers)} subscribers...")
    results = []
    for sub in subscribers:
        result = send_push_notification(sub, message)
        results.append(result)

    sent = sum(1 for r in results if r["status"] == "sent")
    failed = sum(1 for r in results if r["status"] == "error")
    log.info(f"Done. Sent: {sent} | Failed: {failed}")

    if failed:
        log.warning("Some notifications failed to send. Check above for details.")

if __name__ == "__main__":
    send_all_push_notifications()