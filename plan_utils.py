import psycopg2
from datetime import datetime
import os

DATABASE_URL = os.getenv("DATABASE_URL")

def ensure_user_exists(email, plan="FREE"):
    """
    Ensure a user exists in the users table before tracking usage/quota.
    """
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE email=%s", (email,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email, plan) VALUES (%s, %s)", (email, plan))
        conn.commit()
    cur.close()
    conn.close()

def _get_month_start():
    now = datetime.utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

def get_user_id(email):
    # Return normalized email as "user id"
    return email.lower().strip() if email else None

def get_plan(email):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT plan FROM users WHERE email=%s", (email,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return row[0]
    return None

def get_plan_feature(email, feature):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT plan FROM users WHERE email=%s", (email,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        return None
    plan = row[0]
    cur.execute(f"SELECT {feature} FROM plans WHERE name=%s", (plan,))
    feature_row = cur.fetchone()
    cur.close()
    conn.close()
    if feature_row:
        return feature_row[0]
    return None

def get_plan_limits(email):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT
            u.plan,
            p.messages_per_month,
            p.summaries_per_month,
            p.chat_messages_per_month,
            p.travel_alerts_per_month
        FROM users u
        JOIN plans p ON u.plan = p.name
        WHERE u.email = %s
    """, (email,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        # Default to FREE plan quotas if user not found
        return {
            "plan": "FREE",
            "messages_per_month": 5,
            "summaries_per_month": 5,
            "chat_messages_per_month": 5,
            "travel_alerts_per_month": 10,
            "rss_per_session": 2,
            "summaries_per_session": 2
        }
    plan, messages_per_month, summaries_per_month, chat_messages_per_month, travel_alerts_per_month = row

    # You can optionally fetch per-session quotas from the plans table if you add such columns
    # For now, keep these defaults based on your previous logic
    if plan == "FREE":
        rss_per_session = 2
        summaries_per_session = 2
    elif plan == "BASIC":
        rss_per_session = 5
        summaries_per_session = 5
    elif plan == "PRO":
        rss_per_session = 10
        summaries_per_session = 10
    elif plan == "VIP":
        rss_per_session = 20
        summaries_per_session = 20
    else:
        rss_per_session = 2
        summaries_per_session = 2

    return {
        "plan": plan,
        "messages_per_month": messages_per_month,
        "summaries_per_month": summaries_per_month,
        "chat_messages_per_month": chat_messages_per_month,
        "travel_alerts_per_month": travel_alerts_per_month,
        "rss_per_session": rss_per_session,
        "summaries_per_session": summaries_per_session
    }

def get_usage(email):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT messages_used, summaries_used FROM user_usage WHERE email=%s", (email,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    usage = {
        "email": email,
        "messages_used": row[0] if row else 0,
        "summaries_used": row[1] if row else 0,
    }
    return usage

def check_user_message_quota(email, plan_limits):
    """
    Checks if the user is within their messages_per_month quota.
    Returns (ok: bool, message: str)
    """
    ensure_user_exists(email)  # Ensure user exists before tracking
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT messages_used, last_reset FROM user_usage WHERE email=%s", (email,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    used = row[0] if row else 0
    limit = plan_limits.get("messages_per_month")
    if limit is not None and used >= limit:
        return False, "Monthly message quota reached for your plan."
    return True, ""

def increment_user_message_usage(email):
    """
    Increments the user's messages_used counter for the current month.
    """
    ensure_user_exists(email)
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT email FROM user_usage WHERE email=%s", (email,)
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE user_usage SET messages_used = messages_used + 1, last_reset = CURRENT_TIMESTAMP WHERE email=%s",
            (email,)
        )
    else:
        cur.execute(
            "INSERT INTO user_usage (email, messages_used, last_reset) VALUES (%s, 1, CURRENT_TIMESTAMP)",
            (email,)
        )
    conn.commit()
    cur.close()
    conn.close()

def check_user_rss_quota(email, session_id, plan_limits):
    ensure_user_exists(email)
    month = _get_month_start().date()
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT rss_count FROM user_rss_usage WHERE email=%s AND session_id=%s AND month=%s",
        (email, session_id, month)
    )
    row = cur.fetchone()
    used = row[0] if row else 0
    limit_month = plan_limits.get("travel_alerts_per_month")
    limit_session = plan_limits.get("rss_per_session", 2)
    if limit_month is not None and used >= limit_month:
        cur.close()
        conn.close()
        return False, "Monthly RSS quota reached for your plan."
    if limit_session is not None and used >= limit_session:
        cur.close()
        conn.close()
        return False, "Session RSS quota reached for your plan."
    cur.close()
    conn.close()
    return True, ""

def increment_user_rss_usage(email, session_id, plan=None):
    ensure_user_exists(email, plan or "FREE")
    month = _get_month_start().date()
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM user_rss_usage WHERE email=%s AND session_id=%s AND month=%s",
        (email, session_id, month)
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE user_rss_usage SET rss_count = rss_count + 1, last_reset = CURRENT_TIMESTAMP WHERE id=%s",
            (row[0],)
        )
    else:
        cur.execute(
            "INSERT INTO user_rss_usage (email, session_id, plan, rss_count, last_reset, month) VALUES (%s, %s, %s, 1, CURRENT_TIMESTAMP, %s)",
            (email, session_id, plan, month)
        )
    conn.commit()
    cur.close()
    conn.close()

def check_user_summary_quota(email, plan_limits):
    ensure_user_exists(email)
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT summaries_used, last_reset FROM user_usage WHERE email=%s", (email,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    used = row[0] if row else 0
    limit = plan_limits.get("summaries_per_month")
    if limit is not None and used >= limit:
        return False, "Monthly summary quota reached for your plan."
    return True, ""

def increment_user_summary_usage(email):
    ensure_user_exists(email)
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT email FROM user_usage WHERE email=%s", (email,)
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE user_usage SET summaries_used = summaries_used + 1, last_reset = CURRENT_TIMESTAMP WHERE email=%s",
            (email,)
        )
    else:
        cur.execute(
            "INSERT INTO user_usage (email, summaries_used, last_reset) VALUES (%s, 1, CURRENT_TIMESTAMP)",
            (email,)
        )
    conn.commit()
    cur.close()
    conn.close()

def check_session_summary_quota(session_id, plan_limits):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT summaries_used FROM user_sessions WHERE session_id=%s", (session_id,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    used = row[0] if row else 0
    limit = plan_limits.get("summaries_per_session")
    if limit is not None and used >= limit:
        return False, "Session summary quota reached for your plan."
    return True, ""

def increment_session_summary_usage(session_id):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT session_id FROM user_sessions WHERE session_id=%s", (session_id,)
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE user_sessions SET summaries_used = summaries_used + 1 WHERE session_id=%s",
            (session_id,)
        )
    else:
        cur.execute(
            "INSERT INTO user_sessions (session_id, summaries_used, created_at) VALUES (%s, 1, CURRENT_TIMESTAMP)",
            (session_id,)
        )
    conn.commit()
    cur.close()
    conn.close()