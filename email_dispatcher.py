# email_dispatcher.py — paid-only, unmetered • v2025-08-13
from __future__ import annotations
import os
import smtplib
import logging
import json
from email.mime.text import MIMEText
from typing import Optional, List, Dict
from core.config import CONFIG

logger = logging.getLogger("email_dispatcher")
logging.basicConfig(level=CONFIG.security.log_level)

EMAIL_PUSH_ENABLED = CONFIG.email.push_enabled
BREVO_API_KEY = os.getenv("BREVO_API_KEY") or getattr(CONFIG, "brevo_api_key", None)

try:
    from plan_utils import user_has_paid_plan as _is_paid
except Exception:
    def _is_paid(_email: str) -> bool:
        return False

def send_email(user_email: str, to_addr: str, subject: str, html_body: str, from_addr: Optional[str] = None) -> bool:
    """
    Paid-only, opt-in email. Unmetered. First try Brevo; fallback to SMTP.
    """
    if not _is_paid(user_email):
        logger.debug("email dispatch denied: user not on paid plan (%s)", user_email)
        return False
    if not EMAIL_PUSH_ENABLED:
        logger.debug("email dispatch disabled via env")
        return False

    # Prefer Brevo transactional API
    if BREVO_API_KEY:
        try:
            import requests
            sender_email = from_addr or CONFIG.email.email_from or "no-reply@sentinel.local"
            payload = {
                "sender": {"email": sender_email, "name": CONFIG.email.email_from_name or "Sentinel"},
                "to": [{"email": to_addr}],
                "subject": subject,
                "htmlContent": html_body,
            }
            resp = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={
                    "api-key": BREVO_API_KEY,
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                data=json.dumps(payload),
                timeout=20,
            )
            if 200 <= resp.status_code < 300:
                return True
            logger.warning("Brevo send failed: %s %s", resp.status_code, resp.text[:300])
        except Exception as e:
            logger.error("Brevo send_email error: %s", e)

    # Fallback to SMTP if configured
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
        logger.error("SMTP send_email failed: %s", e)
        return False

def send_pdf_report(email: str, region: Optional[str] = None) -> dict:
    """
    Backward-compatible stub for legacy cron usage.
    The system now uses the in-app weekly digest scheduler for PDFs.
    This function avoids ImportError in cron jobs and clearly reports a skip.
    """
    try:
        # Respect paid plan gating if available
        if not _is_paid(email):
            return {"status": "skipped", "reason": "user not on paid plan"}

        # If push is disabled, report skip (matches send_email behavior)
        if not EMAIL_PUSH_ENABLED:
            return {"status": "skipped", "reason": "email push disabled"}

        # No daily PDF generation here; weekly digests handled by APScheduler.
        logger.info(
            "send_pdf_report stub called for %s (region=%s); using weekly digest scheduler",
            email,
            region,
        )
        return {"status": "skipped", "reason": "deprecated; use weekly digest scheduler"}
    except Exception as e:
        logger.warning("send_pdf_report stub error: %s", e)
        return {"status": "error", "reason": str(e)}

def send_bulk(user_email: str, recipients: List[str], subject: str, html_body: str, from_addr: Optional[str] = None) -> Dict[str, bool]:
    """
    Send a generic email to multiple recipients. Uses Brevo if available, else SMTP in a loop.
    Returns a map of recipient -> success boolean.
    """
    results: Dict[str, bool] = {}
    for r in recipients:
        results[r] = send_email(user_email=user_email, to_addr=r, subject=subject, html_body=html_body, from_addr=from_addr)
    return results
