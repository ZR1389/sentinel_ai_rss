# webpush_send.py
from __future__ import annotations
import os
import json
import logging
from typing import Dict, Any, Optional

from pywebpush import webpush, WebPushException

logger = logging.getLogger("webpush_send")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY")
VAPID_PUBLIC_KEY  = os.getenv("VAPID_PUBLIC_KEY")
VAPID_EMAIL       = os.getenv("VAPID_EMAIL", "mailto:security@example.com")

def send_web_push(subscription: Dict[str, Any], payload: Dict[str, Any]) -> Optional[bool]:
    """
    Send a Web Push to a single browser subscription.

    Returns:
      True  -> delivered
      False -> subscription is no longer valid (404/410); caller should delete it
      None  -> other error (transient)
    """
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        logger.warning("Missing VAPID keys; web push disabled.")
        return None

    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_public_key=VAPID_PUBLIC_KEY,
            vapid_claims={"sub": VAPID_EMAIL},
            timeout=10,
        )
        return True
    except WebPushException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (404, 410):
            logger.info("Expired/invalid subscription (remove): %s", subscription.get("endpoint"))
            return False
        logger.error("WebPushException (%s): %s", status, e)
        return None
    except Exception as e:
        logger.error("webpush failed: %s", e)
        return None

def broadcast_to_user(user_email: str, title: str, body: str, url: str = "/dashboard", icon: str = "/logo192.png") -> int:
    """
    Send push notification to all of a user's browser subscriptions.
    
    Args:
        user_email: User email address
        title: Notification title
        body: Notification body text
        url: URL to open when notification is clicked
        icon: Notification icon URL
    
    Returns:
        Number of successful sends
    """
    import psycopg2
    
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        logger.warning("DATABASE_URL not set; skipping push broadcast")
        return 0
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT endpoint, p256dh, auth 
                    FROM web_push_subscriptions 
                    WHERE user_email = %s
                """, (user_email,))
                subs = cur.fetchall()
        
        if not subs:
            logger.debug(f"No push subscriptions for {user_email}")
            return 0
        
        payload = {
            "title": title,
            "body": body,
            "url": url,
            "icon": icon
        }
        
        dead = []
        sent = 0
        
        for row in subs:
            sub = {"endpoint": row[0], "keys": {"p256dh": row[1], "auth": row[2]}}
            result = send_web_push(sub, payload)
            if result is True:
                sent += 1
            elif result is False:
                dead.append(row[0])
        
        # Cleanup expired subscriptions
        if dead:
            with psycopg2.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.executemany(
                        "DELETE FROM web_push_subscriptions WHERE endpoint=%s",
                        [(e,) for e in dead]
                    )
                    conn.commit()
            logger.info(f"Removed {len(dead)} expired push subscriptions for {user_email}")
        
        logger.info(f"Sent {sent} push notifications to {user_email}")
        return sent
    except Exception as e:
        logger.error(f"broadcast_to_user failed for {user_email}: {e}")
        return 0
