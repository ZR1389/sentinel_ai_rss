import psycopg2
from datetime import datetime, date, timedelta
import os
import logging
import json
from uuid import uuid4

from security_log_utils import log_security_event

DATABASE_URL = os.getenv("DATABASE_URL")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

def ensure_user_exists(email, plan="free"):
    if not email:
        logger.warning("No email passed to ensure_user_exists.")
        log_security_event(
            event_type="user_missing",
            email=email,
            details="No email passed to ensure_user_exists"
        )
        return
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE email=%s", (email,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (email, plan) VALUES (%s, %s)", (email, plan))
        conn.commit()
        logger.info(f"Created new user: {email}, plan: {plan}")
        log_security_event(
            event_type="user_created",
            email=email,
            details=f"Created new user with plan {plan}"
        )
    cur.close()
    conn.close()

def _get_month_start():
    now = datetime.utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

def get_user_id(email):
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
        log_security_event(
            event_type="plan_feature_denied",
            email=email,
            details=f"User not found for feature '{feature}'"
        )
        return None
    plan = row[0]
    try:
        cur.execute(f"SELECT {feature} FROM plans WHERE name=%s", (plan,))
        feature_row = cur.fetchone()
    except Exception as e:
        cur.close()
        conn.close()
        log_security_event(
            event_type="plan_feature_denied",
            email=email,
            details=f"Feature '{feature}' lookup error in plan '{plan}': {e}"
        )
        return None
    cur.close()
    conn.close()
    if feature_row:
        return feature_row[0]
    log_security_event(
        event_type="plan_feature_denied",
        email=email,
        details=f"Feature '{feature}' not found in plan '{plan}'"
    )
    return None

def require_plan_feature(email, feature):
    value = get_plan_feature(email, feature)
    if value is None or value is False:
        logger.info(f"User {email} does NOT have feature '{feature}'")
        log_security_event(
            event_type="plan_feature_denied",
            email=email,
            details=f"Feature '{feature}' denied"
        )
        return False
    logger.info(f"User {email} has feature '{feature}'")
    log_security_event(
        event_type="plan_feature_allowed",
        email=email,
        details=f"Feature '{feature}' allowed"
    )
    return True

def get_plan_limits(email):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT
            u.plan,
            p.summaries_per_month,
            p.chat_messages_per_month,
            p.travel_alerts_per_month,
            p.custom_pdf_briefings_frequency,
            p.pdf_reports_per_month,
            p.insights,
            p.telegram,
            p.newsletter
        FROM users u
        JOIN plans p ON u.plan = p.name
        WHERE u.email = %s
    """, (email,))
    row = cur.fetchone()
    colnames = [desc[0] for desc in cur.description]
    cur.close()
    conn.close()
    if not row:
        log_security_event(
            event_type="plan_limits_default",
            email=email,
            details="Returned default limits"
        )
        return {
            "plan": "free",
            "summaries_per_month": 0,
            "chat_messages_per_month": 0,
            "travel_alerts_per_month": 0,
            "custom_pdf_briefings_frequency": None,
            "pdf_reports_per_month": 0,
            "insights": False,
            "telegram": False,
            "newsletter": False
        }
    limits = dict(zip(colnames, row))
    log_security_event(
        event_type="plan_limits_fetched",
        email=email,
        plan=limits.get("plan"),
        details=f"Limits: {limits}"
    )
    return limits

def get_usage(email):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT chat_messages_used, summaries_used, pdf_reports_used FROM user_usage WHERE email=%s", (email,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    usage = {
        "email": email,
        "chat_messages_used": row[0] if row else 0,
        "summaries_used": row[1] if row else 0,
        "pdf_reports_used": row[2] if row and len(row) > 2 else 0,
    }
    log_security_event(
        event_type="usage_fetched",
        email=email,
        details=f"Usage: {usage}"
    )
    return usage

def check_user_message_quota(email, plan_limits):
    ensure_user_exists(email)
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT chat_messages_used, last_reset FROM user_usage WHERE email=%s", (email,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    used = row[0] if row else 0
    limit = plan_limits.get("chat_messages_per_month")
    if limit is not None and used >= limit:
        log_security_event(
            event_type="quota_exceeded",
            email=email,
            details=f"Monthly chat message quota reached. Used: {used}, Limit: {limit}"
        )
        return False, "Monthly chat message quota reached for your plan."
    log_security_event(
        event_type="quota_ok",
        email=email,
        details=f"Chat message quota OK. Used: {used}, Limit: {limit}"
    )
    return True, ""

def increment_user_message_usage(email):
    ensure_user_exists(email)
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT email FROM user_usage WHERE email=%s", (email,)
    )
    row = cur.fetchone()
    if row:
        cur.execute(
            "UPDATE user_usage SET chat_messages_used = chat_messages_used + 1, last_reset = CURRENT_TIMESTAMP WHERE email=%s",
            (email,)
        )
        log_security_event(
            event_type="quota_increment",
            email=email,
            details="Incremented chat_messages_used"
        )
    else:
        cur.execute(
            "INSERT INTO user_usage (email, chat_messages_used, last_reset) VALUES (%s, 1, CURRENT_TIMESTAMP)",
            (email,)
        )
        log_security_event(
            event_type="quota_increment",
            email=email,
            details="Created user_usage row and incremented chat_messages_used"
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
        log_security_event(
            event_type="summary_quota_exceeded",
            email=email,
            details=f"Monthly summary quota reached. Used: {used}, Limit: {limit}"
        )
        return False, "Monthly summary quota reached for your plan."
    log_security_event(
        event_type="summary_quota_ok",
        email=email,
        details=f"Summary quota OK. Used: {used}, Limit: {limit}"
    )
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
        log_security_event(
            event_type="summary_increment",
            email=email,
            details="Incremented summaries_used"
        )
    else:
        cur.execute(
            "INSERT INTO user_usage (email, summaries_used, last_reset) VALUES (%s, 1, CURRENT_TIMESTAMP)",
            (email,)
        )
        log_security_event(
            event_type="summary_increment",
            email=email,
            details="Created user_usage row and incremented summaries_used"
        )
    conn.commit()
    cur.close()
    conn.close()

def check_user_pdf_quota(email, plan_limits):
    ensure_user_exists(email)
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT pdf_reports_used, pdf_reports_last_reset FROM user_usage WHERE email=%s", (email,)
    )
    row = cur.fetchone()
    used = row[0] if row and row[0] is not None else 0
    last_reset = row[1] if row else None

    quota = plan_limits.get("pdf_reports_per_month")
    today = date.today()
    now_month = today.strftime("%Y-%m")
    last_month = None
    if last_reset:
        try:
            last_month = last_reset.strftime("%Y-%m") if isinstance(last_reset, date) else str(last_reset)[:7]
        except Exception:
            last_month = str(last_reset)[:7]
    if last_month != now_month:
        used = 0
        cur.execute(
            "UPDATE user_usage SET pdf_reports_used=0, pdf_reports_last_reset=%s WHERE email=%s",
            (today, email)
        )
        conn.commit()

    if quota is not None and quota > 0 and used >= quota:
        log_security_event(
            event_type="pdf_quota_exceeded",
            email=email,
            details=f"Monthly PDF quota reached. Used: {used}, Limit: {quota}"
        )
        cur.close()
        conn.close()
        return False, "Monthly PDF report quota reached for your plan."
    log_security_event(
        event_type="pdf_quota_ok",
        email=email,
        details=f"PDF quota OK. Used: {used}, Limit: {quota}"
    )
    cur.close()
    conn.close()
    return True, ""

def increment_user_pdf_usage(email):
    ensure_user_exists(email)
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT pdf_reports_used, pdf_reports_last_reset FROM user_usage WHERE email=%s", (email,)
    )
    row = cur.fetchone()
    used = row[0] if row and row[0] is not None else 0
    last_reset = row[1] if row else None

    today = date.today()
    now_month = today.strftime("%Y-%m")
    last_month = None
    if last_reset:
        try:
            last_month = last_reset.strftime("%Y-%m") if isinstance(last_reset, date) else str(last_reset)[:7]
        except Exception:
            last_month = str(last_reset)[:7]
    if last_month != now_month:
        used = 0
        cur.execute(
            "UPDATE user_usage SET pdf_reports_used=1, pdf_reports_last_reset=%s WHERE email=%s",
            (today, email)
        )
    else:
        cur.execute(
            "UPDATE user_usage SET pdf_reports_used = pdf_reports_used + 1, pdf_reports_last_reset=%s WHERE email=%s",
            (today, email)
        )
    conn.commit()
    log_security_event(
        event_type="pdf_quota_increment",
        email=email,
        details="Incremented pdf_reports_used"
    )
    cur.close()
    conn.close()

# --- User Profile Personalization Helpers ---

def fetch_user_profile(email):
    db_url = DATABASE_URL
    if not db_url:
        logger.error("DATABASE_URL not set in environment")
        return {}
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            SELECT email, risk_tolerance, asset_type, preferred_alert_types,
                   country_watchlist, threat_categories, alert_channels,
                   profession, employer, destination, travel_start, travel_end,
                   means_of_transportation, reason_for_travel, custom_fields,
                   preferred_region, preferred_threat_type, home_location, alert_tone
            FROM user_profiles
            WHERE email = %s
            LIMIT 1
        """, (email,))
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return {}
        columns = [desc[0] for desc in cur.description]
        profile = dict(zip(columns, row))
        cur.close()
        conn.close()
        return profile
    except Exception as e:
        logger.error(f"[plan_utils.py] Error fetching user profile: {e}")
        return {}

def save_or_update_user_profile(profile):
    db_url = DATABASE_URL
    if not db_url:
        logger.error("DATABASE_URL not set in environment")
        return False
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        sql = """
        INSERT INTO user_profiles (
            email, risk_tolerance, asset_type, preferred_alert_types,
            country_watchlist, threat_categories, alert_channels,
            profession, employer, destination, travel_start, travel_end,
            means_of_transportation, reason_for_travel, custom_fields,
            preferred_region, preferred_threat_type, home_location, alert_tone
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (email) DO UPDATE SET
            risk_tolerance = EXCLUDED.risk_tolerance,
            asset_type = EXCLUDED.asset_type,
            preferred_alert_types = EXCLUDED.preferred_alert_types,
            country_watchlist = EXCLUDED.country_watchlist,
            threat_categories = EXCLUDED.threat_categories,
            alert_channels = EXCLUDED.alert_channels,
            profession = EXCLUDED.profession,
            employer = EXCLUDED.employer,
            destination = EXCLUDED.destination,
            travel_start = EXCLUDED.travel_start,
            travel_end = EXCLUDED.travel_end,
            means_of_transportation = EXCLUDED.means_of_transportation,
            reason_for_travel = EXCLUDED.reason_for_travel,
            custom_fields = EXCLUDED.custom_fields,
            preferred_region = EXCLUDED.preferred_region,
            preferred_threat_type = EXCLUDED.preferred_threat_type,
            home_location = EXCLUDED.home_location,
            alert_tone = EXCLUDED.alert_tone
        """
        cur.execute(sql, (
            profile.get("email"),
            profile.get("risk_tolerance"),
            profile.get("asset_type"),
            profile.get("preferred_alert_types"),
            profile.get("country_watchlist"),
            profile.get("threat_categories"),
            profile.get("alert_channels"),
            profile.get("profession"),
            profile.get("employer"),
            profile.get("destination"),
            profile.get("travel_start"),
            profile.get("travel_end"),
            profile.get("means_of_transportation"),
            profile.get("reason_for_travel"),
            profile.get("custom_fields"),
            profile.get("preferred_region"),
            profile.get("preferred_threat_type"),
            profile.get("home_location"),
            profile.get("alert_tone")
        ))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"[plan_utils.py] Error saving/updating user profile: {e}")
        return False

def update_user_preferences(email, preferred_region=None, preferred_threat_type=None, home_location=None, alert_tone=None):
    db_url = DATABASE_URL
    if not db_url:
        logger.error("DATABASE_URL not set in environment")
        return False
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        update_fields = []
        params = []
        if preferred_region is not None:
            update_fields.append("preferred_region = %s")
            params.append(preferred_region)
        if preferred_threat_type is not None:
            update_fields.append("preferred_threat_type = %s")
            params.append(preferred_threat_type)
        if home_location is not None:
            update_fields.append("home_location = %s")
            params.append(home_location)
        if alert_tone is not None:
            update_fields.append("alert_tone = %s")
            params.append(alert_tone)
        if not update_fields:
            cur.close()
            conn.close()
            return False
        params.append(email)
        sql = f"UPDATE user_profiles SET {', '.join(update_fields)} WHERE email = %s"
        cur.execute(sql, tuple(params))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"[plan_utils.py] Error updating user preferences: {e}")
        return False

def assign_alert_cluster(region, threat_type, title, published_time):
    db_url = DATABASE_URL
    cluster_id = None
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            SELECT cluster_id FROM alerts
            WHERE region = %s AND type = %s AND title = %s
              AND published BETWEEN %s AND %s
            LIMIT 1
        """, (
            region,
            threat_type,
            title,
            published_time - timedelta(hours=72),
            published_time + timedelta(hours=72),
        ))
        row = cur.fetchone()
        if row and row[0]:
            cluster_id = row[0]
        else:
            cluster_id = str(uuid4())
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"[plan_utils.py] Error assigning cluster ID: {e}")
        cluster_id = str(uuid4())
    return cluster_id

def alert_frequency(region, threat_type, hours=48):
    db_url = DATABASE_URL
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM alerts
            WHERE region = %s AND type = %s
              AND published >= NOW() - INTERVAL '%s hours'
        """, (region, threat_type, hours))
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count
    except Exception as e:
        logger.error(f"[plan_utils.py] Error counting alert frequency: {e}")
        return 0

def get_recent_alerts(region, threat_type, limit=10):
    db_url = DATABASE_URL
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            SELECT title, summary, published FROM alerts
            WHERE region = %s AND type = %s
            ORDER BY published DESC
            LIMIT %s
        """, (region, threat_type, limit))
        alerts = cur.fetchall()
        cur.close()
        conn.close()
        return alerts
    except Exception as e:
        logger.error(f"[plan_utils.py] Error fetching recent alerts: {e}")
        return []

def group_alerts_by_period(period="day", region=None):
    db_url = DATABASE_URL
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        date_trunc = "day"
        if period == "week":
            date_trunc = "week"
        elif period == "month":
            date_trunc = "month"
        sql = f"""
            SELECT date_trunc('{date_trunc}', published) AS period,
                   COUNT(*) as alert_count
            FROM alerts
            {"WHERE region = %s" if region else ""}
            GROUP BY period
            ORDER BY period DESC
        """
        params = (region,) if region else ()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [{"period": r[0], "alert_count": r[1]} for r in rows]
    except Exception as e:
        logger.error(f"[plan_utils.py] Error grouping alerts by period: {e}")
        return []

# ---- ALIAS/STUB FOR fetch_user_preferences ----
def fetch_user_preferences(*args, **kwargs):
    """Stub function for compatibility. If you have a real function, alias it here."""
    # You can replace this with logic to fetch user preferences if needed.
    return {}