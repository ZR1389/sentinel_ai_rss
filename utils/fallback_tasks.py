"""fallback_tasks.py — RQ task functions for fallback jobs.

This module provides the callable enqueued by RQ workers.
"""
from __future__ import annotations

import time
from typing import Optional, Dict, Any
import os, logging
import requests  # type: ignore

def _truthy(v: Optional[str]) -> bool:
    return str(v or '').lower() in {'1','true','yes','on'}

def _notify_failure(payload: Dict[str, Any]) -> None:
    import os, logging
    logger = logging.getLogger(__name__)
    
    # Check if notification should fire based on error type and failure rate threshold
    if not _should_notify(payload):
        logger.info("[fallback_task] Notification suppressed for job %s", payload.get('job_id'))
        return
    
    url = os.getenv('FAILURE_WEBHOOK_URL')
    if not url:
        logger.error("[fallback_task] Failure: %s", payload)
    else:
        try:
            requests.post(url, json={"event": "fallback_job_failed", **payload}, timeout=5)
        except Exception as e:
            logger.error("[fallback_task] Failure webhook error: %s | payload=%s", e, payload)

    # Secondary channels (best-effort, optional)
    _notify_failure_telegram(payload)
    _notify_failure_email(payload)

def _should_notify(payload: Dict[str, Any]) -> bool:
    """Check if notification should fire based on error type and failure rate."""
    import os
    error_str = str(payload.get('error', '')).lower()
    
    # Check error type filters (comma-separated keywords to trigger)
    notify_errors = os.getenv('FAILURE_NOTIFY_ERRORS', 'timeout,connection,rate limit,quota').lower()
    error_keywords = [k.strip() for k in notify_errors.split(',') if k.strip()]
    
    # If no keywords match and filtering is enabled, suppress
    if error_keywords and not any(kw in error_str for kw in error_keywords):
        return False
    
    # Check failure rate threshold (jobs failed in last N minutes)
    try:
        threshold = int(os.getenv('FAILURE_RATE_THRESHOLD', '5'))  # max failures per window
        window_min = int(os.getenv('FAILURE_RATE_WINDOW_MIN', '10'))  # window in minutes
        
        import time
        now = time.time()
        window_sec = window_min * 60
        
        # Track recent failures in module-level cache
        if not hasattr(_should_notify, '_recent_failures'):
            _should_notify._recent_failures = []  # type: ignore
        
        failures = _should_notify._recent_failures  # type: ignore
        # Prune old entries
        failures[:] = [ts for ts in failures if now - ts < window_sec]
        
        # Check if threshold exceeded
        if len(failures) >= threshold:
            return False  # suppress if too many recent failures
        
        # Record this failure
        failures.append(now)
        return True
    except Exception:
        return True  # default to notify on error

def _notify_failure_telegram(payload: Dict[str, Any]) -> None:
    import os, logging
    logger = logging.getLogger(__name__)
    bot_token = os.getenv('FAILURE_TG_BOT_TOKEN')
    chat_id = os.getenv('FAILURE_TG_CHAT_ID')
    if not bot_token or not chat_id:
        return
    text = (
        f"[Fallback Job FAILED]\n"
        f"job_id: {payload.get('job_id')}\n"
        f"country: {payload.get('country')} / {payload.get('region')}\n"
        f"error: {payload.get('error')}\n"
        f"retries_left: {payload.get('retries_left')} of {payload.get('max_retries')}\n"
        f"acting: {payload.get('acting_email')} ({payload.get('acting_plan')})\n"
        f"corr: {payload.get('correlation_id')}\n"
    )
    try:
        import requests
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {"chat_id": chat_id, "text": text}
        resp = requests.post(url, json=data, timeout=10)
        if resp.status_code >= 400:
            logger.error("[fallback_task] Telegram notify failed: %s %s", resp.status_code, resp.text)
    except Exception as e:
        logger.error("[fallback_task] Telegram notify failed: %s", e)

def _notify_failure_email(payload: Dict[str, Any]) -> None:
    import os, logging
    logger = logging.getLogger(__name__)
    to_addr = os.getenv('FAILURE_EMAIL_TO')
    brevo_api_key = os.getenv('BREVO_API_KEY')
    from_addr = os.getenv('BREVO_SENDER_EMAIL', 'info@zikarisk.com')
    from_name = os.getenv('BREVO_SENDER_NAME', 'Sentinel Notifier')
    
    # Prefer centralized dispatcher when available
    try:
        from email_dispatcher import send_email
        html_body = f"<p>{message}</p>"
        ok = send_email(user_email=to_addr, to_addr=to_addr, subject=subject, html_body=html_body, from_addr=from_addr)
        return bool(ok)
    except Exception:
        pass

    if not (to_addr and brevo_api_key):
        logger.warning("[fallback_task] Missing to_addr or BREVO_API_KEY; skipping email")
        return False
    
    subject = f"[Sentinel] Fallback job FAILED ({payload.get('country')}/{payload.get('region')})"
    html = f"""
    <h3>Fallback Job FAILED</h3>
    <ul>
      <li><strong>Job ID:</strong> {payload.get('job_id')}</li>
      <li><strong>Location:</strong> {payload.get('country')} / {payload.get('region')}</li>
      <li><strong>Error:</strong> {payload.get('error')}</li>
      <li><strong>Retries:</strong> {payload.get('retries_left')} of {payload.get('max_retries')}</li>
      <li><strong>Acting User:</strong> {payload.get('acting_email')} ({payload.get('acting_plan')})</li>
      <li><strong>Correlation ID:</strong> {payload.get('correlation_id')}</li>
    </ul>
    """
    
    try:
        import requests
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {
            "api-key": brevo_api_key,
            "Content-Type": "application/json"
        }
        data = {
            "sender": {"name": from_name, "email": from_addr},
            "to": [{"email": to_addr}],
            "subject": subject,
            "htmlContent": html
        }
        resp = requests.post(url, json=data, headers=headers, timeout=10)
        if resp.status_code >= 400:
            logger.error("[fallback_task] Brevo email failed: %s %s", resp.status_code, resp.text)
    except Exception as e:
        logger.error("[fallback_task] Email notify failed: %s", e)

def run_fallback_task(country: str, region: Optional[str]) -> Dict[str, Any]:
    """Execute the real-time fallback with retry-aware failure notifications."""
    t0 = time.time()
    try:
        from real_time_fallback import perform_realtime_fallback
        attempts = perform_realtime_fallback(country=country, region=region)
        t1 = time.time()
        return {
            "country": country,
            "region": region,
            "attempts": attempts,
            "status": "completed",
            "elapsed_ms": int((t1 - t0) * 1000),
            "started_at": t0,
            "finished_at": t1,
        }
    except Exception as e:
        # Try to fetch/augment RQ job meta for reliable final-failure notifications only
        job_id = None
        retries_left = None
        acting_email = None
        acting_plan = None
        correlation_id = None
        max_retries = None
        attempts = None
        try:
            from rq import get_current_job  # type: ignore
            job = get_current_job()
            if job:
                job_id = job.id
                meta = job.meta or {}
                acting_email = meta.get('acting_email')
                acting_plan = meta.get('acting_plan')
                correlation_id = meta.get('correlation_id')
                max_retries = int(meta.get('max_retries', 0))
                # Increment attempts counter in meta for deterministic remaining calc
                attempts = int(meta.get('attempts', 0)) + 1
                meta['attempts'] = attempts
                try:
                    job.meta = meta
                    job.save_meta()
                except Exception:
                    pass
                # Prefer RQ's retries_left if available; otherwise derive
                retries_left = getattr(job, 'retries_left', None)
                if retries_left is None and max_retries:
                    retries_left = max(0, max_retries - attempts)
        except Exception:
            pass

        # Notify only on final failure to reduce noise
        if retries_left in (0, None) and max_retries is not None:
            _notify_failure({
                "job_id": job_id,
                "country": country,
                "region": region,
                "error": str(e),
                "retries_left": retries_left,
                "max_retries": max_retries,
                "attempts": attempts,
                "acting_email": acting_email,
                "acting_plan": acting_plan,
                "correlation_id": correlation_id,
            })
        # Re-raise to allow RQ Retry mechanism to handle backoff
        raise
