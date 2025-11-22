"""Trial management utilities.

Provides helpers to start, end, and periodically check/expire user trials.
Adapted for a psycopg2 environment (no SQLAlchemy). Exposed functions:
  - start_trial(user_dict, plan='PRO')
  - end_trial(user_dict, convert_to_paid=False)
  - check_expired_trials()

The expected `user` argument is a dict-like object with keys:
  id, email, plan, is_trial
Returned structures are plain dictionaries ready for JSON serialization.
"""
from __future__ import annotations
from datetime import datetime, timedelta, date
from typing import Dict, Any
import psycopg2
from psycopg2.extras import RealDictCursor

try:
    from config import CONFIG
    DATABASE_URL = CONFIG.database.url
except Exception:
    DATABASE_URL = None

try:
    from config.plans import TRIAL_CONFIG
except Exception:
    TRIAL_CONFIG = {}

# Optional email dispatcher (graceful fallback)
try:
    from email_dispatcher import send_email  # type: ignore
except Exception:
    def send_email(recipient: str, template: str, context: Dict[str, Any]):  # fallback stub
        pass

# Payment method checker stub (replace with real Stripe logic)
def check_payment_method(user_id: int) -> bool:
    """Return True if user appears to have a payment method (stripe_customer_id present)."""
    if not DATABASE_URL:
        return False
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("SELECT stripe_customer_id FROM users WHERE id=%s", (user_id,))
        row = cur.fetchone()
        return bool(row and row[0])

# ---------------- Internal DB helpers ----------------

def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not configured")
    return psycopg2.connect(DATABASE_URL)

def _fetch_user_by_id(user_id: int) -> Dict[str, Any] | None:
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, email, plan, is_trial, trial_started_at, trial_ends_at FROM users WHERE id=%s", (user_id,))
        return cur.fetchone()

# ---------------- Public API ----------------

def start_trial(user: Dict[str, Any], plan: str = 'PRO') -> Dict[str, Any]:
    """Start a free trial for a user currently on FREE.
    Raises ValueError on invalid state or plan.
    """
    if not user:
        raise ValueError('User object required')
    if user.get('is_trial'):
        raise ValueError('User is already on a trial')
    current_plan = (user.get('plan') or 'FREE').upper()
    if current_plan not in ['FREE', None, '']:
        raise ValueError('Only free users can start trials')

    trial_config = TRIAL_CONFIG.get(plan.upper())
    if not trial_config:
        raise ValueError(f'No trial available for {plan} plan')

    trial_duration = int(trial_config.get('duration_days', 0))
    if trial_duration <= 0:
        raise ValueError('Invalid trial duration configuration')

    trial_ends_at = datetime.utcnow() + timedelta(days=trial_duration)
    plan_upper = plan.upper()

    with _conn() as conn, conn.cursor() as cur:
        # Update user row
        cur.execute(
            """
            UPDATE users
               SET plan = %s,
                   is_trial = TRUE,
                   trial_started_at = NOW(),
                   trial_ends_at = %s
             WHERE id = %s
            """,
            (plan_upper, trial_ends_at, user['id'])
        )
        # Log plan change
        metadata = f'{{"duration_days": {trial_duration}}}'
        cur.execute(
            """
            INSERT INTO plan_changes (user_id, from_plan, to_plan, reason, metadata)
            VALUES (%s, %s, %s, 'trial_start', %s)
            """,
            (user['id'], 'FREE', plan_upper, metadata)
        )
        conn.commit()

    return {
        'trial_started': True,
        'plan': plan_upper,
        'trial_ends_at': trial_ends_at.isoformat() + 'Z'
    }

def end_trial(user: Dict[str, Any], convert_to_paid: bool = False) -> Dict[str, Any]:
    """End a user's trial. If convert_to_paid=True retain plan (mark trial ended), else downgrade to FREE."""
    if not user:
        raise ValueError('User object required')
    if not user.get('is_trial'):
        raise ValueError('User is not on a trial')

    plan_upper = (user.get('plan') or 'FREE').upper()

    with _conn() as conn, conn.cursor() as cur:
        if convert_to_paid:
            # Mark trial concluded, keep plan
            cur.execute(
                """
                UPDATE users
                   SET is_trial = FALSE,
                       trial_started_at = NULL,
                       trial_ends_at = NULL
                 WHERE id = %s
                """,
                (user['id'],)
            )
            cur.execute(
                """
                INSERT INTO plan_changes (user_id, from_plan, to_plan, reason)
                VALUES (%s, %s, %s, 'trial_converted')
                """,
                (user['id'], plan_upper, plan_upper)
            )
            conn.commit()
            return {'trial_converted': True, 'plan': plan_upper}
        else:
            # Downgrade to FREE
            cur.execute(
                """
                UPDATE users
                   SET plan = 'FREE',
                       is_trial = FALSE,
                       trial_started_at = NULL,
                       trial_ends_at = NULL
                 WHERE id = %s
                """,
                (user['id'],)
            )
            cur.execute(
                """
                INSERT INTO plan_changes (user_id, from_plan, to_plan, reason)
                VALUES (%s, %s, 'FREE', 'trial_expired')
                """,
                (user['id'], plan_upper)
            )
            conn.commit()
            return {'trial_expired': True, 'plan': 'FREE'}

def check_expired_trials() -> int:
    """Cron helper: Convert or downgrade all expired trials. Returns number processed."""
    if not DATABASE_URL:
        return 0
    processed = 0
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT id, email, plan, is_trial, trial_ends_at
              FROM users
             WHERE is_trial = TRUE
               AND trial_ends_at < NOW()
            """
        )
        expired = cur.fetchall() or []
    for u in expired:
        has_payment = False
        try:
            has_payment = check_payment_method(u['id'])
        except Exception:
            pass
        # Convert or downgrade
        if has_payment:
            end_trial(u, convert_to_paid=True)
            try:
                send_email(u['email'], 'trial_converted', {'plan': u['plan']})
            except Exception:
                pass
        else:
            end_trial(u, convert_to_paid=False)
            try:
                send_email(u['email'], 'trial_expired', {'plan': 'FREE'})
            except Exception:
                pass
        processed += 1
    return processed

__all__ = ['start_trial','end_trial','check_expired_trials','check_payment_method']
