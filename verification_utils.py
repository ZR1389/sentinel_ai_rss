import time
import psycopg2
import os
from datetime import datetime, timedelta
import requests
from plan_utils import get_plan_limits, check_user_message_quota, ensure_user_exists
from security_log_utils import log_security_event

DATABASE_URL = os.getenv("DATABASE_URL")

# --- Brevo transactional email sender ---
def send_verification_email(email, code, subject, body):
    api_key = os.getenv("BREVO_API_KEY")
    sender_email = os.getenv("BREVO_SENDER_EMAIL", "info@zikarisk.com")
    sender_name = os.getenv("BREVO_SENDER_NAME", "Zika Risk")
    payload = {
        "sender": {"email": sender_email, "name": sender_name},
        "to": [{"email": email}],
        "subject": subject,
        "textContent": body
    }
    headers = {
        "api-key": api_key,
        "Content-Type": "application/json"
    }
    try:
        r = requests.post("https://api.brevo.com/v3/smtp/email", json=payload, headers=headers, timeout=10)
        log_security_event(
            event_type="verification_email_sent" if r.status_code in (200,201) else "verification_email_failed",
            email=email,
            details=f"Status code: {r.status_code}, response: {r.text}"
        )
        return r.status_code in (200, 201)
    except Exception as e:
        log_security_event(
            event_type="verification_email_error",
            email=email,
            details=str(e)
        )
        print(f"Brevo email send error: {e}")
        return False

def set_verification_code(email):
    """
    Generate and store a verification code for an email, valid for 15 minutes.
    Returns the code.
    """
    code = f"{int(time.time_ns() % 1000000):06d}"  # 6-digit code
    expiry = datetime.utcnow() + timedelta(minutes=15)
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO email_verification (email, code, expires_at, verified)
        VALUES (%s, %s, %s, FALSE)
        ON CONFLICT (email) DO UPDATE
        SET code = EXCLUDED.code, expires_at = EXCLUDED.expires_at, verified = FALSE
    """, (email, code, expiry))
    conn.commit()
    cur.close()
    conn.close()
    log_security_event(
        event_type="verification_code_set",
        email=email,
        details=f"Verification code set, expires at {expiry.isoformat()}"
    )
    return code

def send_code_email(email, code=None, subject=None, body=None):
    """
    Generate, store, and send a verification or reset code via email, after checking quota for free users.
    Returns (success, error) tuple.
    """
    ensure_user_exists(email, plan="FREE")  # Ensure the user exists before verification/quota

    plan_limits = get_plan_limits(email)
    plan = plan_limits.get("plan", "FREE")
    if plan == "FREE":
        ok, msg = check_user_message_quota(email, plan_limits)
        if not ok:
            log_security_event(
                event_type="verification_quota_exceeded",
                email=email,
                details=msg
            )
            return False, "Your email address is already in our system and you are out of free messages. If this is a mistake contact us. If you are a member, please log in."
    if code is None:
        code = set_verification_code(email)
    if subject is None:
        subject = "Your Sentinel AI Verification Code"
    if body is None:
        body = f"""
Hello,

Your verification code: {code}

This code is valid for 15 minutes.
If you did not request this, please ignore this message.

Regards,
Sentinel AI by Zika Risk
"""
    sent = send_verification_email(email, code, subject, body)
    if not sent:
        log_security_event(
            event_type="verification_email_send_failed",
            email=email,
            details="Failed to send email"
        )
        return False, "Failed to send email"
    log_security_event(
        event_type="verification_email_send_success",
        email=email,
        details="Verification email sent"
    )
    return True, None

def check_verification_code(email, code):
    """
    Check if code is correct and not expired for given email.
    Returns (True, None) if OK, (False, error_message) if not.
    """
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT code, expires_at, verified FROM email_verification WHERE email=%s
    """, (email,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        log_security_event(
            event_type="verification_code_missing",
            email=email,
            details="No code for this email"
        )
        return False, "No code for this email"
    real_code, expires_at, verified = row
    now = datetime.utcnow()
    if expires_at < now:
        cur.close()
        conn.close()
        log_security_event(
            event_type="verification_code_expired",
            email=email,
            details="Code expired"
        )
        return False, "Code expired"
    if code != real_code:
        cur.close()
        conn.close()
        log_security_event(
            event_type="verification_code_incorrect",
            email=email,
            details="Incorrect code"
        )
        return False, "Incorrect code"
    cur.execute("""
        UPDATE email_verification SET verified=TRUE WHERE email=%s
    """, (email,))
    conn.commit()
    cur.close()
    conn.close()
    log_security_event(
        event_type="verification_code_success",
        email=email,
        details="Code verified successfully"
    )
    return True, None

def get_client_ip(flask_request):
    if 'X-Forwarded-For' in flask_request.headers:
        return flask_request.headers['X-Forwarded-For'].split(',')[0].strip()
    return flask_request.remote_addr

def email_verification_ip_quota_exceeded(ip_address, max_per_hour=5, max_per_day=10):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM email_verification_ip_log WHERE ip_address=%s AND attempted_at > NOW() - INTERVAL '1 hour'", (ip_address,))
    hour_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM email_verification_ip_log WHERE ip_address=%s AND attempted_at > NOW() - INTERVAL '1 day'", (ip_address,))
    day_count = cur.fetchone()[0]
    cur.close()
    conn.close()
    exceeded = hour_count >= max_per_hour or day_count >= max_per_day
    if exceeded:
        log_security_event(
            event_type="verification_ip_quota_exceeded",
            details=f"IP {ip_address} exceeded quota: hour_count={hour_count}, day_count={day_count}"
        )
    else:
        log_security_event(
            event_type="verification_ip_quota_ok",
            details=f"IP {ip_address} within quota: hour_count={hour_count}, day_count={day_count}"
        )
    return exceeded

def log_email_verification_ip(ip_address):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("INSERT INTO email_verification_ip_log (ip_address) VALUES (%s)", (ip_address,))
    conn.commit()
    cur.close()
    conn.close()
    log_security_event(
        event_type="verification_ip_logged",
        details=f"IP {ip_address} logged for verification attempt"
    )