# plan_utils.py — plans, usage & gating • v2025-08-13 (with is_active)

from __future__ import annotations
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
import logging

from security_log_utils import log_security_event  # keep your existing logger

DATABASE_URL = os.getenv("DATABASE_URL")
DEFAULT_PLAN = os.getenv("DEFAULT_PLAN", "FREE").upper()
# Which plans count as “paid” for feature gating (Telegram/Email/Push/PDF)
PAID_PLANS = set(
    p.strip().upper() for p in os.getenv("PAID_PLANS", "PRO,ENTERPRISE").split(",") if p.strip()
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
        cur.execute("SELECT 1 FROM users WHERE email=%s", (email,))
        if not cur.fetchone():
            # Your users table HAS is_active boolean default true — set it explicitly
            cur.execute(
                "INSERT INTO users (email, plan, is_active) VALUES (%s, %s, %s)",
                (email, plan, True),
            )
            log_security_event(event_type="user_created", email=email, details=f"Created new user with plan {plan}")

        # user_usage row (initialize period at start-of-month)
        cur.execute("SELECT 1 FROM user_usage WHERE email=%s", (email,))
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO user_usage (email, chat_messages_used, last_reset) VALUES (%s, %s, %s)",
                (email, 0, _first_of_month_utc().replace(tzinfo=None)),
            )
            log_security_event(event_type="usage_row_created", email=email, details="Initialized user_usage row")
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
                log_security_event(event_type="plan_limits_default", email=email, details="Inactive or no plan; default limits")
                return {"plan": "FREE", "chat_messages_per_month": 0}
            plan, msgs = row[0], row[1]
            limits = {"plan": (plan or "FREE").upper(), "chat_messages_per_month": int(msgs or 0)}
            log_security_event(event_type="plan_limits_fetched", email=email, plan=limits["plan"], details=f"Limits: {limits}")
            return limits
    except Exception as e:
        logger.error("get_plan_limits error: %s", e)
        log_security_event(event_type="plan_limits_error", email=email, details=str(e))
        return {"plan": "FREE", "chat_messages_per_month": 0}


# ---------------------------- Usage (chat-only metering) ----------------------------

def _maybe_monthly_reset(email: str) -> None:
    """
    If last_reset is prior to current month, reset usage to 0 and set last_reset to first-of-month.
    """
    anchor = _first_of_month_utc().replace(tzinfo=None)
    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT chat_messages_used, last_reset FROM user_usage WHERE email=%s", (email,))
        row = cur.fetchone()
        if not row:
            # initialize row (should have been created in ensure_user_exists)
            cur.execute(
                "INSERT INTO user_usage (email, chat_messages_used, last_reset) VALUES (%s, %s, %s)",
                (email, 0, anchor),
            )
            conn.commit()
            return
        _, last_reset = row
        if last_reset is None or last_reset < anchor:
            cur.execute(
                "UPDATE user_usage SET chat_messages_used = 0, last_reset = %s WHERE email=%s",
                (anchor, email),
            )
            conn.commit()
            log_security_event(event_type="usage_monthly_reset", email=email, details=f"Reset usage at {anchor.isoformat()}")


def get_usage(email: str) -> dict:
    email = _sanitize_email(email)
    if not email:
        return {"email": None, "chat_messages_used": 0}

    # ensure row and maybe reset
    ensure_user_exists(email)
    _maybe_monthly_reset(email)

    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT chat_messages_used FROM user_usage WHERE email=%s", (email,))
        row = cur.fetchone()
        usage = {"email": email, "chat_messages_used": int(row[0]) if row else 0}
        log_security_event(event_type="usage_fetched", email=email, details=f"Usage: {usage}")
        return usage


def check_user_message_quota(email: str, plan_limits: dict) -> tuple[bool, str]:
    """
    Return (ok, msg). Performs monthly reset check before enforcing quota.
    """
    email = _sanitize_email(email)
    ensure_user_exists(email)
    _maybe_monthly_reset(email)

    with _conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT chat_messages_used FROM user_usage WHERE email=%s", (email,))
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
    log_security_event(event_type="quota_ok", email=email, details=f"Used: {used}, Limit: {limit}")
    return True, ""


def increment_user_message_usage(email: str) -> None:
    """
    Increments usage by 1 (AFTER a successful advisory).
    Does NOT change last_reset (only resets at month boundary).
    """
    email = _sanitize_email(email)
    ensure_user_exists(email)
    _maybe_monthly_reset(email)

    with _conn() as conn, conn.cursor() as cur:
        # upsert-like behavior
        cur.execute("SELECT 1 FROM user_usage WHERE email=%s", (email,))
        if cur.fetchone():
            cur.execute(
                "UPDATE user_usage SET chat_messages_used = chat_messages_used + 1 WHERE email=%s",
                (email,),
            )
            log_security_event(event_type="quota_increment", email=email, details="Incremented chat_messages_used")
        else:
            cur.execute(
                "INSERT INTO user_usage (email, chat_messages_used, last_reset) VALUES (%s, %s, %s)",
                (email, 1, _first_of_month_utc().replace(tzinfo=None)),
            )
            log_security_event(event_type="quota_increment", email=email, details="Created user_usage and incremented")
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
