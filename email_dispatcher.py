# email_dispatcher.py — paid-only, unmetered • v2025-08-13
from __future__ import annotations
import os
import smtplib
import logging
from email.mime.text import MIMEText
from typing import Optional
from config import CONFIG

logger = logging.getLogger("email_dispatcher")
logging.basicConfig(level=CONFIG.security.log_level)

EMAIL_PUSH_ENABLED = CONFIG.email.push_enabled

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

    host = CONFIG.email.smtp_host
    port = CONFIG.email.smtp_port
    user = CONFIG.email.smtp_user
    pwd  = CONFIG.email.smtp_pass
    use_tls = CONFIG.email.smtp_tls
    from_addr = from_addr or CONFIG.email.email_from or user or "no-reply@sentinel.local"

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
