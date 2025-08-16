# verification_utils.py — robust + graceful email verification
import os, random, string
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional

try:
    import requests
except Exception:
    requests = None  # still works in dev mode (no email)

try:
    from db_utils import fetch_one, fetch_all, execute
except Exception:
    fetch_one = fetch_all = execute = None

BREVO_API_KEY      = os.getenv("BREVO_API_KEY", "").strip()
VERIFY_FROM_EMAIL  = (os.getenv("VERIFY_FROM_EMAIL") or os.getenv("SENDER_EMAIL") or "").strip()
SITE_NAME          = os.getenv("SITE_NAME", "Zika Risk / Sentinel AI")

CODE_TTL_MIN       = int(os.getenv("VERIFY_CODE_TTL_MIN", "20"))
IP_WINDOW_MIN      = int(os.getenv("VERIFY_IP_WINDOW_MIN", "10"))
IP_MAX_REQUESTS    = int(os.getenv("VERIFY_IP_MAX_REQUESTS", "6"))

def _now():
    return datetime.now(timezone.utc)

def _ensure_tables():
    if execute is None:
        raise RuntimeError("DB helpers unavailable")
    execute("""
    CREATE TABLE IF NOT EXISTS email_verification_codes (
      email      TEXT NOT NULL,
      code       TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      expires_at TIMESTAMPTZ NOT NULL,
      PRIMARY KEY (email, code)
    );
    """, ())
    execute("""
    CREATE TABLE IF NOT EXISTS email_verification_ip_log (
      ip    TEXT NOT NULL,
      ts    TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """, ())

def _recent_ip_count(ip: str) -> int:
    if fetch_one is None:
        return 0
    # param-safe interval: now() - ('<minutes> minutes')::interval
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
        "SELECT 1 FROM email_verification_codes WHERE email=%s AND code=%s AND expires_at > now() LIMIT 1",
        (email, code),
    )
    return bool(row)

def _clear_codes(email: str):
    if execute is None:
        return
    execute("DELETE FROM email_verification_codes WHERE email=%s", (email,))

def _mark_verified(email: str):
    if execute is None:
        return False
    try:
        execute("UPDATE users SET email_verified=TRUE WHERE email=%s", (email,))
        return True
    except Exception:
        return False

def _send_via_brevo(to_email: str, code: str) -> Tuple[bool, str]:
    # If not configured, we still succeed (dev mode) so UX isn’t blocked.
    if not BREVO_API_KEY or not VERIFY_FROM_EMAIL or not requests:
        return True, "Dev mode: code generated (email not sent)"
    payload = {
        "sender": {"email": VERIFY_FROM_EMAIL, "name": SITE_NAME},
        "to": [{"email": to_email}],
        "subject": f"{SITE_NAME} – Your verification code",
        "htmlContent": f"<p>Your verification code is:</p><h2>{code}</h2>"
                       f"<p>This code expires in {CODE_TTL_MIN} minutes.</p>",
    }
    r = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": BREVO_API_KEY, "accept": "application/json", "content-type": "application/json"},
        json=payload,
        timeout=15,
    )
    if 200 <= r.status_code < 300:
        return True, "Sent"
    return False, f"Email send failed ({r.status_code})"

def issue_verification_code(email: str, ip_address: Optional[str] = None) -> Tuple[bool, str]:
    try:
        _ensure_tables()
        ip = (ip_address or "").strip() or "unknown"
        if _recent_ip_count(ip) >= IP_MAX_REQUESTS:
            return False, "Too many requests from this IP. Please wait and try again."
        code = "".join(random.choices(string.digits, k=6))
        _put_code(email, code)
        _log_ip(ip)
        ok, msg = _send_via_brevo(email, code)
        if ok:
            return True, "Verification code sent."
        return False, msg
    except Exception as e:
        return False, f"Server error: {e}"

def verify_code(email: str, code: str) -> Tuple[bool, str]:
    try:
        if not _check_code(email, code):
            return False, "Invalid or expired code."
        _mark_verified(email)
        _clear_codes(email)
        return True, "Email verified."
    except Exception as e:
        return False, f"Server error: {e}"

def verification_status(email: str) -> Tuple[bool, Optional[str]]:
    if fetch_one is None:
        return False, None
    row = fetch_one("SELECT email_verified FROM users WHERE email=%s", (email,))
    return bool(row and (row[0] is True)), None
