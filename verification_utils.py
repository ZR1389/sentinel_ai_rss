# verification_utils.py — email verification via Brevo (idempotent schema + IP rate-limiting)

import os
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional

# Optional HTTP client for Brevo
try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # Dev fallback will still let verification flow proceed

# DB helpers provided by your app
try:
    from db_utils import fetch_one, fetch_all, execute
except Exception:  # pragma: no cover
    fetch_one = fetch_all = execute = None

# ---- Config (env) ----
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "").strip()
# Sender identity (prefer VERIFY_FROM_EMAIL/SITE_NAME; fall back to older names)
VERIFY_FROM_EMAIL = (os.getenv("VERIFY_FROM_EMAIL") or os.getenv("BREVO_SENDER_EMAIL") or os.getenv("SENDER_EMAIL") or "").strip()
SITE_NAME = (os.getenv("SITE_NAME") or os.getenv("BREVO_SENDER_NAME") or "Zika Risk / Sentinel AI").strip()

# Throttling + expiry
CODE_TTL_MIN    = int(os.getenv("VERIFY_CODE_TTL_MIN", "20"))  # minutes a code is valid
IP_WINDOW_MIN   = int(os.getenv("VERIFY_IP_WINDOW_MIN", "10")) # lookback window
IP_MAX_REQUESTS = int(os.getenv("VERIFY_IP_MAX_REQUESTS", "6"))# max sends per IP per window

# ---- Helpers ----
def _now() -> datetime:
    return datetime.now(timezone.utc)

def _ensure_tables():
    """
    Idempotent schema ensure + lightweight migration for:
      - email_verification_codes
      - email_verification_ip_log

    Final target schemas:

      email_verification_codes (
        email      TEXT NOT NULL,
        code       TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (email, code)
      )

      email_verification_ip_log (
        id   SERIAL PRIMARY KEY,
        ip   TEXT NOT NULL,
        ts   TIMESTAMPTZ NOT NULL DEFAULT now()
      )
    """
    if execute is None or fetch_one is None:
        raise RuntimeError("DB helpers unavailable")

    # 1) Codes table
    execute("""
    CREATE TABLE IF NOT EXISTS email_verification_codes (
      email      TEXT NOT NULL,
      code       TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      expires_at TIMESTAMPTZ NOT NULL,
      PRIMARY KEY (email, code)
    );
    """, ())

    # 2) IP log table (target shape)
    execute("""
    CREATE TABLE IF NOT EXISTS email_verification_ip_log (
      id SERIAL PRIMARY KEY,
      ip TEXT NOT NULL,
      ts TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """, ())

    # 2a) Ensure columns exist (covers legacy installs)
    execute("ALTER TABLE email_verification_ip_log ADD COLUMN IF NOT EXISTS ip TEXT;", ())
    execute("ALTER TABLE email_verification_ip_log ADD COLUMN IF NOT EXISTS ts TIMESTAMPTZ NOT NULL DEFAULT now();", ())

    # 2b) Legacy columns detection (your previous accidental schema)
    legacy_ip_col = fetch_one("""
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema='public' AND table_name='email_verification_ip_log' AND column_name='ip_address'
      LIMIT 1
    """, ())
    legacy_ts_col = fetch_one("""
      SELECT 1
      FROM information_schema.columns
      WHERE table_schema='public' AND table_name='email_verification_ip_log' AND column_name='attempted_at'
      LIMIT 1
    """, ())

    # 2c) Backfill ip from ip_address if missing
    if legacy_ip_col:
        execute("""
          UPDATE email_verification_ip_log
          SET ip = ip_address
          WHERE ip IS NULL AND ip_address IS NOT NULL
        """, ())

    # 2d) Backfill ts from attempted_at if present
    if legacy_ts_col:
        execute("""
          UPDATE email_verification_ip_log
          SET ts = attempted_at
          WHERE attempted_at IS NOT NULL
            AND (ts IS NULL OR ts = attempted_at OR ts >= attempted_at)
        """, ())

    # (Optional) You can drop legacy cols once you're confident:
    # execute("ALTER TABLE email_verification_ip_log DROP COLUMN IF EXISTS ip_address;", ())
    # execute("ALTER TABLE email_verification_ip_log DROP COLUMN IF EXISTS attempted_at;", ())

def _recent_ip_count(ip: str) -> int:
    if fetch_one is None:
        return 0
    # Param-safe interval: now() - (<minutes> minutes)::interval
    row = fetch_one(
        "SELECT count(*) FROM email_verification_ip_log "
        "WHERE ip=%s AND ts > now() - (%s || ' minutes')::interval",
        (ip, str(IP_WINDOW_MIN)),
    )
    return int(row[0]) if row else 0

def _log_ip(ip: str):
    if execute is None:
        return
    execute("INSERT INTO email_verification_ip_log (ip) VALUES (%s)", (ip,))

def _put_code(email: str, code: str):
    if execute is None:
        raise RuntimeError("DB helpers unavailable")
    expires = _now() + timedelta(minutes=CODE_TTL_MIN)
    execute(
        "INSERT INTO email_verification_codes (email, code, expires_at) VALUES (%s, %s, %s)",
        (email, code, expires),
    )

def _check_code(email: str, code: str) -> bool:
    if fetch_one is None:
        return False
    row = fetch_one(
        "SELECT 1 FROM email_verification_codes "
        "WHERE email=%s AND code=%s AND expires_at > now() LIMIT 1",
        (email, code),
    )
    return bool(row)

def _clear_codes(email: str):
    if execute is None:
        return
    execute("DELETE FROM email_verification_codes WHERE email=%s", (email,))

def _mark_verified(email: str) -> bool:
    if execute is None:
        return False
    try:
        execute("UPDATE users SET email_verified=TRUE WHERE email=%s", (email,))
        return True
    except Exception:
        return False

def _send_via_brevo(to_email: str, code: str) -> Tuple[bool, str]:
    """
    Sends the code via Brevo. If not configured, we still return success so the flow
    isn’t blocked in dev (user can paste the code surfaced by logs, etc).
    """
    if not BREVO_API_KEY or not VERIFY_FROM_EMAIL or not requests:
        # Dev fallback
        return True, "Dev mode: code generated (email not sent)"
    payload = {
        "sender": {"email": VERIFY_FROM_EMAIL, "name": SITE_NAME},
        "to": [{"email": to_email}],
        "subject": f"{SITE_NAME} – Your verification code",
        "htmlContent": (
            f"<p>Your verification code is:</p>"
            f"<h2 style='font-family:monospace;letter-spacing:2px'>{code}</h2>"
            f"<p>This code expires in {CODE_TTL_MIN} minutes.</p>"
        ),
    }
    r = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={
            "api-key": BREVO_API_KEY,
            "accept": "application/json",
            "content-type": "application/json",
        },
        json=payload,
        timeout=15,
    )
    if 200 <= r.status_code < 300:
        return True, "Sent"
    return False, f"Email send failed ({r.status_code})"

# ---- Public functions used by main.py ----
def issue_verification_code(email: str, ip_address: Optional[str] = None) -> Tuple[bool, str]:
    """
    Create & store a 6-digit code, log the IP (rate-limited), and send via Brevo.
    Returns (ok, message).
    """
    try:
        _ensure_tables()
        ip = (ip_address or "").strip() or "unknown"

        # rate limit per IP
        if _recent_ip_count(ip) >= IP_MAX_REQUESTS:
            return False, "Too many requests from this IP. Please wait and try again."

        # issue code
        code = "".join(random.choices(string.digits, k=6))
        _put_code(email, code)
        _log_ip(ip)

        ok, msg = _send_via_brevo(email, code)
        if ok:
            return True, "Verification code sent."
        # If Brevo fails, the code is still stored; caller can try again.
        return False, msg
    except Exception as e:
        return False, f"Server error: {e}"

def verify_code(email: str, code: str) -> Tuple[bool, str]:
    """
    Validate a code; if valid, mark user verified and clear codes for that email.
    """
    try:
        if not _check_code(email, code):
            return False, "Invalid or expired code."
        _mark_verified(email)
        _clear_codes(email)
        return True, "Email verified."
    except Exception as e:
        return False, f"Server error: {e}"

def verification_status(email: str) -> Tuple[bool, Optional[str]]:
    """
    Returns (is_verified, None). Kept for compatibility with main.py.
    """
    if fetch_one is None:
        return False, None
    row = fetch_one("SELECT email_verified FROM users WHERE email=%s", (email,))
    return bool(row and (row[0] is True)), None
