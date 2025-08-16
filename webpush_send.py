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
