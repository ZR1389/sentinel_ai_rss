# plan_utils.py — plans, usage & gating • v2025-08-13 (with is_active) - FIXED for user_id

from __future__ import annotations
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
import logging

from security_log_utils import log_security_event  # keep your existing logger
from config import CONFIG

DATABASE_URL = CONFIG.database.url
DEFAULT_PLAN = CONFIG.app.default_plan.upper()
# Which plans count as "paid" for feature gating (Telegram/Email/Push/PDF)
PAID_PLANS = set(
    p.strip().upper() for p in CONFIG.app.paid_plans.split(",") if p.strip()
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ---------------------------- DB helpers ----------------------------

def _conn():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(DATABASE_URL)

def _first_of_month_utc(dt: datetime | None = None) -> datetime:
    dt = dt or datetime.now(timezone.utc)
    return datetime(dt.year, dt.month, 1, tzinfo=timezone.utc)

def _sanitize_email(email: str | None) -> str | None:
    if not email or not isinstance(email, str):
        return None
    e = email.strip().lower()
    return e if e and "@" in e else None

def _get_user_id(email: str) -> int | None:
    """Get user_id from email"""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        row = cur.fetchone()
        return row[0] if row else None


# ---------------------------- Users & Plans ----------------------------

def ensure_user_exists(email: str, plan: str = DEFAULT_PLAN) -> None:
    email = _sanitize_email(email)
    if not email:
        logger.warning("No email passed to ensure_user_exists.")
        log_security_event(event_type="user_missing", email=email, details="No email passed to ensure_user_exists")
        return

    plan = (plan or DEFAULT_PLAN).upper()
    with _conn() as conn, conn.cursor() as cur:
        # users row
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        row = cur.fetchone()
        if not row:
            # Your users table HAS is_active boolean default true — set it explicitly
            cur.execute(
                "INSERT INTO users (email, plan, is_active) VALUES (%s, %s, %s) RETURNING id",
                (email, plan, True),
            )
            user_id = cur.fetchone()[0]
            log_security_event(event_type="user_created", email=email, details=f"Created new user with plan {plan}")
        else:
            user_id = row[0]

        # user_usage row (initialize period at start-of-month)
        cur.execute("SELECT 1 FROM user_usage WHERE user_id=%s", (user_id,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO user_usage (user_id, chat_messages_used, last_reset) VALUES (%s, %s, %s)",
                (user_id, 0, _first_of_month_utc().replace(tzinfo=None)),
            )
            logger.info("Initialized user_usage row for %s", email)
        conn.commit()


def get_plan(email: str) -> str | None:
    email = _sanitize_email(email)
    if not email:
        return None
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT plan FROM users WHERE email=%s", (email,))
        row = cur.fetchone()
        return (row[0] if row else None)


def get_plan_limits(email: str) -> dict:
    """
    Returns { plan: PLAN, chat_messages_per_month: int }.
    - If the user is missing or INACTIVE, falls back to FREE with 0 limit.
    """
    email = _sanitize_email(email)
    if not email:
        return {"plan": "FREE", "chat_messages_per_month": 0}

    try:
        with _conn() as conn, conn.cursor() as cur:
            # Require active users to pick up their plan limits.
            cur.execute("""
                SELECT u.plan, p.chat_messages_per_month
                FROM users u
                JOIN plans p ON UPPER(u.plan) = UPPER(p.name)
                WHERE u.email = %s
                  AND COALESCE(u.is_active, TRUE) = TRUE
            """, (email,))
            row = cur.fetchone()
            if not row:
                logger.warning("get_plan_limits: Inactive or no plan for %s; using default limits", email)
                return {"plan": "FREE", "chat_messages_per_month": 0}
            plan, msgs = row[0], row[1]
            return {"plan": (plan or "FREE").upper(), "chat_messages_per_month": int(msgs or 0)}
    except Exception as e:
        logger.error("get_plan_limits error: %s", e)
        log_security_event(event_type="plan_limits_error", email=email, details=str(e))
        return {"plan": "FREE", "chat_messages_per_month": 0}


# ---------------------------- Usage (chat-only metering) ----------------------------

def _maybe_monthly_reset(email: str) -> None:
    """
    If last_reset is prior to current month, reset usage to 0 and set last_reset to first-of-month.
    """
    user_id = _get_user_id(email)
    if not user_id:
        return
        
    anchor = _first_of_month_utc().replace(tzinfo=None)
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT chat_messages_used, last_reset FROM user_usage WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
        if not row:
            # initialize row (should have been created in ensure_user_exists)
            cur.execute(
                "INSERT INTO user_usage (user_id, chat_messages_used, last_reset) VALUES (%s, %s, %s)",
                (user_id, 0, anchor),
            )
            conn.commit()
            return
        _, last_reset = row
        if last_reset is None or last_reset < anchor:
            cur.execute(
                "UPDATE user_usage SET chat_messages_used = 0, last_reset = %s WHERE user_id=%s",
                (anchor, user_id),
            )
            conn.commit()
            logger.info("Monthly usage reset for %s at %s", email, anchor.isoformat())


def get_usage(email: str) -> dict:
    email = _sanitize_email(email)
    if not email:
        return {"email": None, "chat_messages_used": 0}

    # ensure row and maybe reset
    ensure_user_exists(email)
    _maybe_monthly_reset(email)
    
    user_id = _get_user_id(email)
    if not user_id:
        return {"email": email, "chat_messages_used": 0}

    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT chat_messages_used FROM user_usage WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
        return {"email": email, "chat_messages_used": int(row[0]) if row else 0}


def check_user_message_quota(email: str, plan_limits: dict) -> tuple[bool, str]:
    """
    Return (ok, msg). Performs monthly reset check before enforcing quota.
    """
    email = _sanitize_email(email)
    ensure_user_exists(email)
    _maybe_monthly_reset(email)
    
    user_id = _get_user_id(email)
    if not user_id:
        return False, "User not found"

    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT chat_messages_used FROM user_usage WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
        used = int(row[0]) if row else 0

    limit = plan_limits.get("chat_messages_per_month")
    limit = 0 if limit is None else int(limit)

    if limit >= 0 and used >= limit:
        log_security_event(
            event_type="quota_exceeded",
            email=email,
            details=f"Monthly chat quota reached. Used: {used}, Limit: {limit}",
        )
        return False, "Monthly chat message quota reached for your plan."
    
    # Only log if approaching limit (>90%)
    if limit > 0 and used / limit > 0.9:
        logger.warning("User %s approaching quota limit: %d/%d (%.1f%%)", email, used, limit, (used/limit)*100)
    
    return True, ""


def increment_user_message_usage(email: str) -> None:
    """
    Increments usage by 1 (AFTER a successful advisory).
    Does NOT change last_reset (only resets at month boundary).
    """
    email = _sanitize_email(email)
    ensure_user_exists(email)
    _maybe_monthly_reset(email)
    
    user_id = _get_user_id(email)
    if not user_id:
        return

    with _conn() as conn, conn.cursor() as cur:
        # upsert-like behavior
        cur.execute("SELECT 1 FROM user_usage WHERE user_id=%s", (user_id,))
        if cur.fetchone():
            cur.execute(
                "UPDATE user_usage SET chat_messages_used = chat_messages_used + 1 WHERE user_id=%s",
                (user_id,),
            )
        else:
            cur.execute(
                "INSERT INTO user_usage (user_id, chat_messages_used, last_reset) VALUES (%s, %s, %s)",
                (user_id, 1, _first_of_month_utc().replace(tzinfo=None)),
            )
        conn.commit()


# ---------------------------- Paid-feature gating ----------------------------

def user_has_paid_plan(email: str) -> bool:
    """
    Returns True if the user is ACTIVE and on a paid plan (defaults: PRO/ENTERPRISE).
    Safe fallback to False on any error.
    """
    email = _sanitize_email(email)
    if not email:
        return False
    try:
        with _conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT plan, COALESCE(is_active, TRUE) FROM users WHERE email=%s LIMIT 1", (email,))
            row = cur.fetchone()
            if not row:
                return False
            plan = (row[0] or "").upper()
            is_active = bool(row[1])
            return is_active and plan in PAID_PLANS
    except Exception as e:
        logger.error("user_has_paid_plan error: %s", e)
        return False


def require_paid_feature(email: str) -> tuple[bool, str]:
    """
    Helper for endpoints that expose paid-only features.
    Returns (ok, message). No metering here.
    """
    if not _sanitize_email(email):
        return False, "Login required."
    if not user_has_paid_plan(email):
        return False, "This feature is available to paid plans."
    return True, ""