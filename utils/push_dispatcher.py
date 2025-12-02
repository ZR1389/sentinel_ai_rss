# push_dispatcher.py — paid-only, unmetered • v2025-08-13
from __future__ import annotations
import os
import logging
from typing import Dict, Any

logger = logging.getLogger("push_dispatcher")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

PUSH_ENABLED = os.getenv("PUSH_ENABLED", "false").lower() in ("1","true","yes","y")

try:
    from utils.plan_utils import user_has_paid_plan as _is_paid
except Exception:
    def _is_paid(_email: str) -> bool:
        return False

# Optional: wire your actual FCM/APNS libs here
def send_push(user_email: str, device_token: str, payload: Dict[str, Any]) -> bool:
    """
    Paid-only, opt-in mobile push. Unmetered.
    """
    if not _is_paid(user_email):
        logger.debug("push denied: user not on paid plan (%s)", user_email)
        return False
    if not PUSH_ENABLED:
        logger.debug("push disabled via env")
        return False

    try:
        # TODO: implement real FCM/APNS call here
        logger.info("Pretend push to %s: %s", device_token, payload)
        return True
    except Exception as e:
        logger.error("send_push failed: %s", e)
        return False
