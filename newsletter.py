# newsletter.py — open to all logged-in (verified) users, unmetered • v2025-08-13

from __future__ import annotations
import os
import re
import requests
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone

from security_log_utils import log_security_event

# -------- Config --------
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
NEWSLETTER_LIST_ID = int(os.getenv("NEWSLETTER_LIST_ID", "3"))
DATABASE_URL = os.getenv("DATABASE_URL")
HTTP_TIMEOUT = float(os.getenv("NEWSLETTER_HTTP_TIMEOUT", "12"))

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("newsletter")

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# -------- Helpers --------
def _sanitize_email(email: str | None) -> str | None:
    if not email or not isinstance(email, str):
        return None
    e = email.strip().lower()
    return e if EMAIL_REGEX.match(e or "") else None

def _db_conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL)

def _user_is_logged_in_and_verified(email: str) -> tuple[bool, str]:
    """
    Requires a row in users(email=...) and is_active = true.
    If users.email_verified exists, it must be true as well.
    Returns (ok, reason_if_not_ok).
    """
    try:
        with _db_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            # Try to fetch email_verified if present; fall back if column missing
            try:
                cur.execute("SELECT is_active, email_verified FROM users WHERE email=%s LIMIT 1", (email,))
                row = cur.fetchone()
                if not row:
                    return False, "User not found. Please sign up / log in."
                is_active = bool(row.get("is_active", True))
                email_verified = row.get("email_verified")
                if not is_active:
                    return False, "Account is inactive."
                # If column exists (value not None), enforce verification
                if email_verified is not None and not bool(email_verified):
                    return False, "Email not verified."
                return True, ""
            except psycopg2.errors.UndefinedColumn:
                # Column doesn't exist → require presence + is_active only
                conn.rollback()
                cur.execute("SELECT is_active FROM users WHERE email=%s LIMIT 1", (email,))
                row2 = cur.fetchone()
                if not row2:
                    return False, "User not found. Please sign up / log in."
                if not bool(row2.get("is_active", True)):
                    return False, "Account is inactive."
                return True, ""
    except Exception as e:
        logger.error("Verification check failed: %s", e)
        return False, "Service error during verification."

# -------- Public API --------
def subscribe_to_newsletter(email: str) -> bool:
    """
    Subscribes the given email to your Brevo *general* newsletter list.
    Requirements:
      - User must be logged in (exists in users) and active.
      - If users.email_verified exists, it must be TRUE.
    No plan required. Not metered.
    """
    sanitized = _sanitize_email(email)
    if not sanitized:
        log_security_event(event_type="newsletter_invalid_email", email=email, details="Invalid email format")
        logger.info("❌ Invalid email")
        return False

    if not BREVO_API_KEY:
        log_security_event(event_type="newsletter_api_key_missing", email=sanitized, details="BREVO_API_KEY not set")
        logger.warning("❌ BREVO_API_KEY not set")
        return False

    # Require login + (verified if column exists)
    ok, reason = _user_is_logged_in_and_verified(sanitized)
    if not ok:
        log_security_event(event_type="newsletter_auth_failed", email=sanitized, details=reason)
        logger.info("❌ %s", reason)
        return False

    url = "https://api.brevo.com/v3/contacts"
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json",
    }

    payload = {
        "email": sanitized,
        "listIds": [NEWSLETTER_LIST_ID],
        "updateEnabled": True,  # idempotent re-subscribe/update
        # You may add attributes only if they are defined in Brevo, otherwise you'll get 400:
        # "attributes": {"SOURCE": "sentinel", "CONSENT_AT": datetime.now(timezone.utc).isoformat()}
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=HTTP_TIMEOUT)
    except requests.RequestException as e:
        log_security_event(event_type="newsletter_subscribe_failed", email=sanitized, details=f"HTTP error: {e}")
        logger.error("❌ Newsletter subscription HTTP error: %s", e)
        return False

    if r.status_code in (201, 204):
        log_security_event(event_type="newsletter_subscribed", email=sanitized, details=f"OK {r.status_code}")
        logger.info("✅ %s subscribed to newsletter.", sanitized)
        return True

    # Brevo sometimes returns 400 for "Contact already exists" if updateEnabled wasn't honored by API version.
    # Surface the response for debugging:
    detail = (r.text or "").strip()
    log_security_event(event_type="newsletter_subscribe_failed", email=sanitized, details=f"{r.status_code}: {detail}")
    logger.warning("❌ Newsletter subscription failed (%s): %s", r.status_code, detail)
    return False


# Optional helper for UI to check eligibility quickly (no network call)
def newsletter_eligibility(email: str) -> dict:
    """
    Returns a small dict your UI can use to enable/disable the subscribe button.
    { "eligible": bool, "reason": "" }
    """
    sanitized = _sanitize_email(email)
    if not sanitized:
        return {"eligible": False, "reason": "Invalid email."}
    ok, reason = _user_is_logged_in_and_verified(sanitized)
    return {"eligible": ok, "reason": reason or ""}
