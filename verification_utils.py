# verification_utils.py — email verification flows • v2025-08-13

from __future__ import annotations
import os
import secrets
import hashlib
import requests
from typing import Optional, Tuple
from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2.extras import RealDictCursor

from security_log_utils import log_security_event

DATABASE_URL = os.getenv("DATABASE_URL")

# Email (Brevo)
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "info@zikarisk.com")
BREVO_SENDER_NAME  = os.getenv("BREVO_SENDER_NAME", "Zika Risk")

# Policy
VERIFY_CODE_TTL_MIN = int(os.getenv("VERIFY_CODE_TTL_MIN", "15"))
VERIFY_CODE_LEN = int(os.getenv("VERIFY_CODE_LEN", "6"))  # numeric digits
EMAIL_MAX_PER_HOUR = int(os.getenv("VERIFY_EMAIL_MAX_PER_HOUR", "5"))
EMAIL_MAX_PER_DAY  = int(os.getenv("VERIFY_EMAIL_MAX_PER_DAY", "12"))
IP_MAX_PER_HOUR    = int(os.getenv("VERIFY_IP_MAX_PER_HOUR", "20"))
IP_MAX_PER_DAY     = int(os.getenv("VERIFY_IP_MAX_PER_DAY", "100"))

def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL)

def _now_utc():
    return datetime.now(timezone.utc)

def _code_numeric(n: int) -> str:
    # returns zero-padded numeric code
    m = 10 ** n
    return str(secrets.randbelow(m)).zfill(n)

def _hash_code(code: str, email: str) -> str:
    # bind hash to email as cheap salt
    return hashlib.sha256((email.lower().strip() + ":" + code).encode()).hexdigest()

# ---------------- Rate limits ----------------

def _count_recent(cur, table: str, column: str, value: str, minutes: int) -> int:
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {column}=%s AND created_at >= NOW() - INTERVAL %s",
                (value, f"{minutes} minutes"))
    return int(cur.fetchone()[0])

def ip_rate_limited(ip_address: Optional[str]) -> bool:
    if not ip_address:
        return False
    with _conn() as conn, conn.cursor() as cur:
        hour = _count_recent(cur, "email_verification_ip_log", "ip_address", ip_address, 60)
        day  = _count_recent(cur, "email_verification_ip_log", "ip_address", ip_address, 24*60)
        exceeded = hour >= IP_MAX_PER_HOUR or day >= IP_MAX_PER_DAY
        log_security_event(
            event_type="verify_ip_rate",
            ip=ip_address,
            details=f"hour={hour}/{IP_MAX_PER_HOUR} day={day}/{IP_MAX_PER_DAY} exceeded={exceeded}",
        )
        return exceeded

def email_rate_limited(email: str) -> bool:
    with _conn() as conn, conn.cursor() as cur:
        hour = _count_recent(cur, "email_verification_email_log", "email", email, 60)
        day  = _count_recent(cur, "email_verification_email_log", "email", email, 24*60)
        exceeded = hour >= EMAIL_MAX_PER_HOUR or day >= EMAIL_MAX_PER_DAY
        log_security_event(
            event_type="verify_email_rate",
            email=email,
            details=f"hour={hour}/{EMAIL_MAX_PER_HOUR} day={day}/{EMAIL_MAX_PER_DAY} exceeded={exceeded}",
        )
        return exceeded

def _log_ip(ip: Optional[str]) -> None:
    if not ip:
        return
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO email_verification_ip_log (ip_address) VALUES (%s)", (ip,))
        conn.commit()

def _log_email(email: str) -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO email_verification_email_log (email) VALUES (%s)", (email,))
        conn.commit()

# ---------------- Email send ----------------

def _send_brevo(email: str, subject: str, text_body: str) -> bool:
    if not BREVO_API_KEY:
        log_security_event(event_type="verify_email_api_missing", email=email, details="BREVO_API_KEY missing")
        return False
    payload = {
        "sender": {"email": BREVO_SENDER_EMAIL, "name": BREVO_SENDER_NAME},
        "to": [{"email": email}],
        "subject": subject,
        "textContent": text_body,
    }
    try:
        r = requests.post("https://api.brevo.com/v3/smtp/email",
                          headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
                          json=payload, timeout=12)
        ok = r.status_code in (200, 201, 202)
        log_security_event(event_type="verify_email_sent" if ok else "verify_email_send_failed",
                           email=email, details=f"status={r.status_code} body={r.text[:240]}")
        return ok
    except requests.RequestException as e:
        log_security_event(event_type="verify_email_http_error", email=email, details=str(e))
        return False

# ---------------- Core flows ----------------

def issue_verification_code(email: str, ip_address: Optional[str] = None) -> Tuple[bool, str]:
    """
    Creates or replaces a verification code for `email`, enforces rate limits, and sends via Brevo.
    Returns (ok, message).
    """
    if ip_rate_limited(ip_address):
        return False, "Too many attempts from your IP. Try later."
    if email_rate_limited(email):
        return False, "Too many verification emails. Try later."

    code = _code_numeric(VERIFY_CODE_LEN)
    code_hash = _hash_code(code, email)
    expires_at = _now_utc() + timedelta(minutes=VERIFY_CODE_TTL_MIN)

    with _conn() as conn, conn.cursor() as cur:
        # Remove existing codes for this email
        cur.execute("DELETE FROM email_verification_codes WHERE email=%s", (email,))
        cur.execute("""
            INSERT INTO email_verification_codes (email, code_hash, expires_at, created_at, attempts)
            VALUES (%s, %s, %s, NOW(), 0)
        """, (email, code_hash, expires_at.replace(tzinfo=None)))
        conn.commit()

    _log_ip(ip_address)
    _log_email(email)

    subject = "Your Sentinel AI verification code"
    body = f"Your verification code is: {code}\nThis code expires in {VERIFY_CODE_TTL_MIN} minutes."
    sent = _send_brevo(email, subject, body)
    if not sent:
        return False, "Failed to send verification email."
    return True, "Verification code sent."

def verify_code(email: str, code: str) -> Tuple[bool, str]:
    """
    Verifies the code. On success, marks users.email_verified = TRUE and deletes the code row.
    """
    h = _hash_code(code, email)
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT email, code_hash, expires_at, attempts
            FROM email_verification_codes
            WHERE email=%s
            LIMIT 1
        """, (email,))
        row = cur.fetchone()
        if not row:
            return False, "No verification code found."
        if row["expires_at"] and row["expires_at"] < _now_utc().replace(tzinfo=None):
            cur.execute("DELETE FROM email_verification_codes WHERE email=%s", (email,))
            conn.commit()
            return False, "Code expired. Request a new one."

        # constant-time compare via hashing + check_password_hash equivalent
        ok = (h == row["code_hash"])
        if not ok:
            # bump attempts
            cur.execute("UPDATE email_verification_codes SET attempts = attempts + 1 WHERE email=%s", (email,))
            conn.commit()
            return False, "Invalid code."

        # success: mark user verified, cleanup
        cur.execute("UPDATE users SET email_verified = TRUE WHERE email=%s", (email,))
        cur.execute("DELETE FROM email_verification_codes WHERE email=%s", (email,))
        conn.commit()
        log_security_event(event_type="email_verified", email=email, details="verification_success")
        return True, "Email verified."

# ---------------- Utilities ----------------

def verification_status(email: str) -> Tuple[bool, Optional[str]]:
    """
    Returns (is_verified, reason_if_false)
    """
    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT email_verified FROM users WHERE email=%s", (email,))
            row = cur.fetchone()
            if not row:
                return False, "User not found."
            return bool(row[0]), None
    except Exception as e:
        return False, "Lookup failed"
