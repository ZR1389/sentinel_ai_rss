# email_dispatcher.py — paid-only, unmetered • v2025-08-13
from __future__ import annotations
import os
import smtplib
import logging
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger("email_dispatcher")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

EMAIL_PUSH_ENABLED = os.getenv("EMAIL_PUSH_ENABLED", "false").lower() in ("1","true","yes","y")

try:
    from plan_utils import user_has_paid_plan as _is_paid
except Exception:
    def _is_paid(_email: str) -> bool:
        return False

def send_email(user_email: str, to_addr: str, subject: str, html_body: str, from_addr: Optional[str] = None) -> bool:
    """
    Paid-only, opt-in email. Unmetered. Returns False if not allowed or disabled.
    """
    if not _is_paid(user_email):
        logger.debug("email dispatch denied: user not on paid plan (%s)", user_email)
        return False
    if not EMAIL_PUSH_ENABLED:
        logger.debug("email dispatch disabled via env")
        return False

    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    pwd  = os.getenv("SMTP_PASS")
    use_tls = os.getenv("SMTP_TLS", "true").lower() in ("1","true","yes","y")
    from_addr = from_addr or os.getenv("EMAIL_FROM", user or "no-reply@sentinel.local")

    if not host or not user or not pwd:
        logger.warning("SMTP creds missing; skipping email dispatch")
        return False

    try:
        msg = MIMEText(html_body, "html", "utf-8")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr

        with smtplib.SMTP(host, port, timeout=20) as s:
            if use_tls:
                s.starttls()
            s.login(user, pwd)
            s.sendmail(from_addr, [to_addr], msg.as_string())
        return True
    except Exception as e:
        logger.error("send_email failed: %s", e)
        return False
