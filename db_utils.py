"""
Database utility functions for Zika Risk platform.

- Only use fetch_raw_alerts_from_db for ingestion and threat engine enrichment.
- Only use fetch_alerts_from_db for downstream consumption (advisor, API, UI, reporting).
- Never use fetch_raw_alerts_from_db for advisor or UI/clients.
- Never use fetch_alerts_from_db for further enrichment—alerts table is the final, best, scored product.
"""

import os
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime, timedelta
import uuid
import logging
from plan_utils import require_plan_feature
from security_log_utils import log_security_event

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
if RAILWAY_ENV:
    log.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    log.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

def get_db_url():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        log.error("DATABASE_URL not set in environment")
    return db_url

# --- USER PROFILE UTILITIES ---

def fetch_user_profile(email):
    db_url = get_db_url()
    if not db_url:
        return {}
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            SELECT email, profession, employer, destination, travel_start, travel_end, means_of_transportation,
                   reason_for_travel, custom_fields, created_at, updated_at, risk_tolerance, asset_type, preferred_alert_types
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
        log.error(f"[db_utils.py] Error fetching user profile: {e}")
        return {}

def fetch_full_user_profile(email):
    db_url = get_db_url()
    if not db_url:
        return {}
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            SELECT *
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
        log.error(f"[db_utils.py] Error fetching full user profile: {e}")
        return {}

def save_or_update_user_profile(profile):
    db_url = get_db_url()
    if not db_url:
        return False
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        sql = """
        INSERT INTO user_profiles (
            email, profession, employer, destination, travel_start, travel_end,
            means_of_transportation, reason_for_travel, custom_fields, risk_tolerance,
            asset_type, preferred_alert_types, updated_at, preferred_region,
            preferred_threat_type, home_location, alert_tone, country_watchlist,
            threat_categories, alert_channels
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (email) DO UPDATE SET
            profession = EXCLUDED.profession,
            employer = EXCLUDED.employer,
            destination = EXCLUDED.destination,
            travel_start = EXCLUDED.travel_start,
            travel_end = EXCLUDED.travel_end,
            means_of_transportation = EXCLUDED.means_of_transportation,
            reason_for_travel = EXCLUDED.reason_for_travel,
            custom_fields = EXCLUDED.custom_fields,
            risk_tolerance = EXCLUDED.risk_tolerance,
            asset_type = EXCLUDED.asset_type,
            preferred_alert_types = EXCLUDED.preferred_alert_types,
            updated_at = EXCLUDED.updated_at,
            preferred_region = EXCLUDED.preferred_region,
            preferred_threat_type = EXCLUDED.preferred_threat_type,
            home_location = EXCLUDED.home_location,
            alert_tone = EXCLUDED.alert_tone,
            country_watchlist = EXCLUDED.country_watchlist,
            threat_categories = EXCLUDED.threat_categories,
            alert_channels = EXCLUDED.alert_channels
        """
        cur.execute(sql, (
            profile.get("email"),
            profile.get("profession"),
            profile.get("employer"),
            profile.get("destination"),
            profile.get("travel_start"),
            profile.get("travel_end"),
            profile.get("means_of_transportation"),
            profile.get("reason_for_travel"),
            profile.get("custom_fields"),
            profile.get("risk_tolerance"),
            profile.get("asset_type"),
            profile.get("preferred_alert_types"),
            datetime.utcnow(),
            profile.get("preferred_region"),
            profile.get("preferred_threat_type"),
            profile.get("home_location"),
            profile.get("alert_tone"),
            profile.get("country_watchlist"),
            profile.get("threat_categories"),
            profile.get("alert_channels")
        ))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        log.error(f"[db_utils.py] Error saving/updating user profile: {e}")
        return False

def update_user_preferences(email, preferred_region=None, preferred_threat_type=None, home_location=None, alert_tone=None):
    db_url = get_db_url()
    if not db_url:
        return False
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        fields = []
        params = []
        if preferred_region is not None:
            fields.append("preferred_region = %s")
            params.append(preferred_region)
        if preferred_threat_type is not None:
            fields.append("preferred_threat_type = %s")
            params.append(preferred_threat_type)
        if home_location is not None:
            fields.append("home_location = %s")
            params.append(home_location)
        if alert_tone is not None:
            fields.append("alert_tone = %s")
            params.append(alert_tone)
        if not fields:
            cur.close()
            conn.close()
            return False
        params.append(email)
        sql = f"UPDATE user_profiles SET {', '.join(fields)} WHERE email = %s"
        cur.execute(sql, tuple(params))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        log.error(f"[db_utils.py] Error updating user preferences: {e}")
        return False

def update_user_watchlist(email, country_watchlist=None, threat_categories=None, alert_channels=None):
    db_url = get_db_url()
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        fields = []
        params = []
        if country_watchlist is not None:
            fields.append("country_watchlist = %s")
            params.append(country_watchlist)
        if threat_categories is not None:
            fields.append("threat_categories = %s")
            params.append(threat_categories)
        if alert_channels is not None:
            fields.append("alert_channels = %s")
            params.append(alert_channels)
        if not fields:
            cur.close()
            conn.close()
            return False
        params.append(email)
        sql = f"UPDATE user_profiles SET {', '.join(fields)} WHERE email = %s"
        cur.execute(sql, tuple(params))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        log.error(f"[db_utils.py] Error updating user watchlist: {e}")
        return False

def save_user_threat_preferences(email, prefs):
    db_url = get_db_url()
    if not db_url:
        return False
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute(
            "UPDATE user_profiles SET threat_preferences = %s WHERE email = %s",
            (prefs, email)
        )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        log.error(f"Error saving user threat preferences: {e}")
        return False

def fetch_user_threat_preferences(email):
    db_url = get_db_url()
    if not db_url:
        return {}
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute(
            "SELECT threat_preferences FROM user_profiles WHERE email = %s",
            (email,)
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0]:
            return row[0]
        return {}
    except Exception as e:
        log.error(f"Error fetching user threat preferences: {e}")
        return {}

# --- ALERTS/INCIDENTS LOGIC ---

def save_raw_alerts_to_db(alerts):
    db_url = get_db_url()
    if not db_url:
        log_security_event(
            event_type="db_config_error",
            details="DATABASE_URL not set for save_raw_alerts_to_db"
        )
        raise Exception("DATABASE_URL not set in environment")
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        log_security_event(
            event_type="db_connection_error",
            details=f"Could not connect to DB: {e}"
        )
        raise
    cur = conn.cursor()

    columns = [
        "uuid", "title", "summary", "en_snippet", "link", "source", "published",
        "region", "country", "city", "ingested_at", "tags"
    ]

    values = []
    for alert in alerts:
        alert_uuid = alert.get("uuid")
        if not alert_uuid:
            alert_uuid = str(uuid.uuid4())
        elif isinstance(alert_uuid, uuid.UUID):
            alert_uuid = str(alert_uuid)
        alert["uuid"] = alert_uuid

        if not alert.get("ingested_at"):
            alert["ingested_at"] = datetime.utcnow()

        tags = alert.get("tags")
        if tags is not None and isinstance(tags, str):
            import ast
            try:
                tags = ast.literal_eval(tags)
            except Exception:
                tags = [tags]
        if tags is not None and not isinstance(tags, list):
            tags = [tags]
        alert["tags"] = tags

        row = [alert.get(col) for col in columns]
        values.append(row)

    sql = f"""
    INSERT INTO raw_alerts ({", ".join(columns)})
    VALUES %s
    ON CONFLICT (uuid) DO UPDATE SET
        title = EXCLUDED.title,
        summary = EXCLUDED.summary,
        en_snippet = EXCLUDED.en_snippet,
        link = EXCLUDED.link,
        source = EXCLUDED.source,
        published = EXCLUDED.published,
        region = EXCLUDED.region,
        country = EXCLUDED.country,
        city = EXCLUDED.city,
        ingested_at = EXCLUDED.ingested_at,
        tags = EXCLUDED.tags
    ;
    """
    try:
        execute_values(cur, sql, values)
        conn.commit()
        log_security_event(
            event_type="raw_alerts_saved",
            details=f"Inserted/updated {len(values)} raw alerts"
        )
    except Exception as e:
        conn.rollback()
        log_security_event(
            event_type="raw_alerts_save_error",
            details=str(e)
        )
        raise
    finally:
        cur.close()
        conn.close()

def fetch_raw_alerts_from_db(region=None, country=None, city=None, start_time=None, end_time=None, limit=1000):
    db_url = get_db_url()
    if not db_url:
        log_security_event(
            event_type="db_config_error",
            details="DATABASE_URL not set for fetch_raw_alerts_from_db"
        )
        raise Exception("DATABASE_URL not set in environment")
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        log_security_event(
            event_type="db_connection_error",
            details=f"Could not connect to DB: {e}"
        )
        raise
    cur = conn.cursor()

    base_sql = "SELECT * FROM raw_alerts WHERE 1=1"
    params = []

    if region:
        base_sql += " AND region = %s"
        params.append(region)
    if country:
        base_sql += " AND country = %s"
        params.append(country)
    if city:
        base_sql += " AND city = %s"
        params.append(city)
    if start_time:
        base_sql += " AND published >= %s"
        params.append(start_time)
    if end_time:
        base_sql += " AND published <= %s"
        params.append(end_time)

    base_sql += " ORDER BY published DESC NULLS LAST LIMIT %s"
    params.append(limit)

    try:
        cur.execute(base_sql, params)
        rows = cur.fetchall()
        colnames = [desc[0] for desc in cur.description]
        results = [dict(zip(colnames, row)) for row in rows]
        log_security_event(
            event_type="raw_alerts_fetched",
            details=f"Fetched {len(results)} raw alerts"
        )
    except Exception as e:
        log_security_event(
            event_type="raw_alerts_fetch_error",
            details=str(e)
        )
        raise
    finally:
        cur.close()
        conn.close()
    return results

def save_alerts_to_db(alerts):
    db_url = get_db_url()
    if not db_url:
        log_security_event(
            event_type="db_config_error",
            details="DATABASE_URL not set for save_alerts_to_db"
        )
        raise Exception("DATABASE_URL not set in environment")
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        log_security_event(
            event_type="db_connection_error",
            details=f"Could not connect to DB: {e}"
        )
        raise
    cur = conn.cursor()

    columns = [
        "uuid", "title", "summary", "en_snippet", "gpt_summary", "link", "source", "published",
        "region", "country", "city", "type", "type_confidence", "threat_level", "threat_label",
        "score", "confidence", "reasoning", "review_flag", "review_notes", "ingested_at",
        "model_used", "sentiment", "forecast", "legal_risk", "cyber_ot_risk",
        "environmental_epidemic_risk", "keyword_weight", "tags", "trend_score", "trend_score_msg",
        "is_anomaly", "early_warning_indicators", "series_id", "incident_series", "historical_context",
        "incident_cluster_id"
    ]

    values = []
    for alert in alerts:
        alert_uuid = alert.get("uuid")
        if not alert_uuid:
            alert_uuid = str(uuid.uuid4())
        elif isinstance(alert_uuid, uuid.UUID):
            alert_uuid = str(alert_uuid)
        alert["uuid"] = alert_uuid

        if not alert.get("ingested_at"):
            alert["ingested_at"] = datetime.utcnow()

        tags = alert.get("tags")
        if tags is not None and isinstance(tags, str):
            import ast
            try:
                tags = ast.literal_eval(tags)
            except Exception:
                tags = [tags]
        if tags is not None and not isinstance(tags, list):
            tags = [tags]
        alert["tags"] = tags

        incident_cluster_id = alert.get("incident_cluster_id")
        if incident_cluster_id is None:
            incident_cluster_id = None
        alert["incident_cluster_id"] = incident_cluster_id

        row = [alert.get(col) for col in columns]
        values.append(row)

    sql = f"""
    INSERT INTO alerts ({", ".join(columns)})
    VALUES %s
    ON CONFLICT (uuid) DO UPDATE SET
        title = EXCLUDED.title,
        summary = EXCLUDED.summary,
        en_snippet = EXCLUDED.en_snippet,
        gpt_summary = EXCLUDED.gpt_summary,
        link = EXCLUDED.link,
        source = EXCLUDED.source,
        published = EXCLUDED.published,
        region = EXCLUDED.region,
        country = EXCLUDED.country,
        city = EXCLUDED.city,
        type = EXCLUDED.type,
        type_confidence = EXCLUDED.type_confidence,
        threat_level = EXCLUDED.threat_level,
        threat_label = EXCLUDED.threat_label,
        score = EXCLUDED.score,
        confidence = EXCLUDED.confidence,
        reasoning = EXCLUDED.reasoning,
        review_flag = EXCLUDED.review_flag,
        review_notes = EXCLUDED.review_notes,
        ingested_at = EXCLUDED.ingested_at,
        model_used = EXCLUDED.model_used,
        sentiment = EXCLUDED.sentiment,
        forecast = EXCLUDED.forecast,
        legal_risk = EXCLUDED.legal_risk,
        cyber_ot_risk = EXCLUDED.cyber_ot_risk,
        environmental_epidemic_risk = EXCLUDED.environmental_epidemic_risk,
        keyword_weight = EXCLUDED.keyword_weight,
        tags = EXCLUDED.tags,
        trend_score = EXCLUDED.trend_score,
        trend_score_msg = EXCLUDED.trend_score_msg,
        is_anomaly = EXCLUDED.is_anomaly,
        early_warning_indicators = EXCLUDED.early_warning_indicators,
        series_id = EXCLUDED.series_id,
        incident_series = EXCLUDED.incident_series,
        historical_context = EXCLUDED.historical_context,
        incident_cluster_id = EXCLUDED.incident_cluster_id
    ;
    """
    try:
        execute_values(cur, sql, values)
        conn.commit()
        log_security_event(
            event_type="alerts_saved",
            details=f"Inserted/updated {len(values)} enriched alerts"
        )
    except Exception as e:
        conn.rollback()
        log_security_event(
            event_type="alerts_save_error",
            details=str(e)
        )
        raise
    finally:
        cur.close()
        conn.close()

def assign_alert_cluster(region, threat_type, title, published_time):
    db_url = get_db_url()
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            SELECT incident_cluster_id FROM alerts
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
            cluster_id = str(uuid.uuid4())
        cur.close()
        conn.close()
        return cluster_id
    except Exception as e:
        log.error(f"Error assigning cluster ID: {e}")
        return str(uuid.uuid4())

def fetch_alerts_from_db(region=None, country=None, city=None, threat_level=None, threat_label=None,
                         start_time=None, end_time=None, limit=100, email=None, days_back=None):
    if email and not require_plan_feature(email, "insights"):
        log_security_event(
            event_type="alerts_plan_denied",
            email=email,
            details="User does not have insights feature, fetch denied"
        )
        return []

    db_url = get_db_url()
    if not db_url:
        log_security_event(
            event_type="db_config_error",
            details="DATABASE_URL not set for fetch_alerts_from_db"
        )
        raise Exception("DATABASE_URL not set in environment")
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        log_security_event(
            event_type="db_connection_error",
            details=f"Could not connect to DB: {e}"
        )
        raise
    cur = conn.cursor()

    base_sql = "SELECT * FROM alerts WHERE 1=1"
    params = []

    if region:
        base_sql += " AND region = %s"
        params.append(region)
    if country:
        base_sql += " AND country = %s"
        params.append(country)
    if city:
        base_sql += " AND city = %s"
        params.append(city)
    if threat_level:
        base_sql += " AND threat_level = %s"
        params.append(threat_level)
    if threat_label:
        base_sql += " AND threat_label = %s"
        params.append(threat_label)
    if start_time:
        base_sql += " AND published >= %s"
        params.append(start_time)
    if end_time:
        base_sql += " AND published <= %s"
        params.append(end_time)
    if days_back is not None:
        since = datetime.utcnow() - timedelta(days=days_back)
        base_sql += " AND published >= %s"
        params.append(since)

    base_sql += " ORDER BY published DESC NULLS LAST LIMIT %s"
    params.append(limit)

    try:
        cur.execute(base_sql, params)
        rows = cur.fetchall()
        colnames = [desc[0] for desc in cur.description]
        results = [dict(zip(colnames, row)) for row in rows]
        log_security_event(
            event_type="alerts_fetched",
            email=email,
            details=f"Fetched {len(results)} enriched alerts"
        )
    except Exception as e:
        log_security_event(
            event_type="alerts_fetch_error",
            email=email,
            details=str(e)
        )
        raise
    finally:
        cur.close()
        conn.close()
    return results

def fetch_past_incidents(region=None, category=None, days=30, limit=20):
    db_url = get_db_url()
    if not db_url:
        log_security_event(
            event_type="db_config_error",
            details="DATABASE_URL not set for fetch_past_incidents"
        )
        raise Exception("DATABASE_URL not set in environment")
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        log_security_event(
            event_type="db_connection_error",
            details=f"Could not connect to DB: {e}"
        )
        raise
    cur = conn.cursor()

    where_clauses = []
    params = []
    if region:
        where_clauses.append("region = %s")
        params.append(region)
    if category:
        where_clauses.append("category = %s")
        params.append(category)
    since = datetime.utcnow() - timedelta(days=days)
    where_clauses.append("published >= %s")
    params.append(since)
    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    query = f"""
        SELECT uuid, title, summary, region, category, subcategory, score, label, published AS timestamp
        FROM alerts
        WHERE {where_sql}
        ORDER BY published DESC
        LIMIT %s
    """
    params.append(limit)
    try:
        cur.execute(query, tuple(params))
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        incidents = [dict(zip(columns, row)) for row in rows]
        cur.close()
        conn.close()
        return incidents
    except Exception as e:
        log_security_event(
            event_type="past_incidents_fetch_error",
            details=str(e)
        )
        return []

def fetch_incident_clusters(region=None, keywords=None, hours_window=72, limit=10):
    db_url = get_db_url()
    if not db_url:
        return []
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        return []
    cur = conn.cursor()

    since = datetime.utcnow() - timedelta(hours=hours_window)
    base_sql = "SELECT region, array_agg(DISTINCT unnest(tags)) as keywords, MIN(published) as start_time, MAX(published) as end_time, array_agg(uuid) as alert_uuids FROM alerts WHERE published >= %s"
    params = [since]

    if region:
        base_sql += " AND region = %s"
        params.append(region)
    if keywords and isinstance(keywords, list) and keywords:
        base_sql += " AND tags && %s"
        params.append(keywords)

    base_sql += " GROUP BY region ORDER BY end_time DESC LIMIT %s"
    params.append(limit)

    try:
        cur.execute(base_sql, params)
        rows = cur.fetchall()
        clusters = []
        for row in rows:
            clusters.append({
                "region": row[0],
                "keywords": row[1],
                "start_time": row[2],
                "end_time": row[3],
                "alert_uuids": row[4]
            })
        cur.close()
        conn.close()
        return clusters
    except Exception as e:
        log.error(f"[db_utils.py] Error in fetch_incident_clusters: {e}")
        return []

def save_region_trend(region, city, trend_window_start, trend_window_end, incident_count, categories=None):
    db_url = get_db_url()
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        sql = """
        INSERT INTO region_trends (region, city, trend_window_start, trend_window_end, incident_count, categories, last_updated)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (region, city, trend_window_start, trend_window_end) DO UPDATE SET
            incident_count = EXCLUDED.incident_count,
            categories = EXCLUDED.categories,
            last_updated = EXCLUDED.last_updated
        """
        cur.execute(sql, (
            region,
            city,
            trend_window_start,
            trend_window_end,
            incident_count,
            categories,
            datetime.utcnow()
        ))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        log.error(f"[db_utils.py] Error saving region trend: {e}")
        return False

def fetch_region_trends(region=None, city=None, start_time=None, end_time=None, limit=20):
    db_url = get_db_url()
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        sql = "SELECT region, city, trend_window_start, trend_window_end, incident_count, categories, last_updated FROM region_trends WHERE 1=1"
        params = []
        if region:
            sql += " AND region = %s"
            params.append(region)
        if city:
            sql += " AND city = %s"
            params.append(city)
        if start_time:
            sql += " AND trend_window_start >= %s"
            params.append(start_time)
        if end_time:
            sql += " AND trend_window_end <= %s"
            params.append(end_time)
        sql += " ORDER BY trend_window_end DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        trends = [dict(zip(columns, row)) for row in rows]
        cur.close()
        conn.close()
        return trends
    except Exception as e:
        log.error(f"[db_utils.py] Error fetching region trends: {e}")
        return []

def get_regional_trend(region: str, days: int = 7, city: str = None) -> dict:
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=days)
    trends = fetch_region_trends(region=region, city=city, start_time=start_time, end_time=end_time, limit=100)
    total_incidents = sum(t.get('incident_count', 0) for t in trends)
    categories = set()
    for t in trends:
        if t.get('categories'):
            categories.update(t['categories'])
    trend_direction = "unknown"
    if len(trends) >= 2:
        first = trends[-1]['incident_count']
        last = trends[0]['incident_count']
        if last > first:
            trend_direction = "increasing"
        elif last < first:
            trend_direction = "decreasing"
        else:
            trend_direction = "stable"
    return {
        "region": region,
        "city": city,
        "days": days,
        "incident_count": total_incidents,
        "categories": list(categories),
        "trend_direction": trend_direction,
        "trend_windows": trends,
    }

def group_alerts_by_period(period="day", region=None):
    db_url = get_db_url()
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
        log.error(f"Error grouping alerts by period: {e}")
        return []

def alert_frequency(region, threat_type, hours=48):
    db_url = get_db_url()
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
        log.error(f"Error counting alert frequency: {e}")
        return 0

def get_recent_alerts(region, threat_type, limit=10):
    db_url = get_db_url()
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
        log.error(f"Error fetching recent alerts: {e}")
        return []

def link_similar_alerts(alert_id, min_score=0.3, days=14, limit=10):
    db_url = get_db_url()
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("SELECT uuid, matched_keywords, city, region, country, category, subcategory, summary FROM alerts WHERE uuid = %s LIMIT 1", (alert_id,))
        ref = cur.fetchone()
        if not ref:
            cur.close()
            conn.close()
            return []
        ref_dict = dict(zip([desc[0] for desc in cur.description], ref))
        since = datetime.utcnow() - timedelta(days=days)
        cur.execute(
            """
            SELECT uuid, matched_keywords, city, region, country, category, subcategory, summary
            FROM alerts
            WHERE published >= %s
              AND uuid != %s
              AND (
                  city = %s OR region = %s OR country = %s
              )
              AND category = %s
            LIMIT %s
            """,
            (since, alert_id, ref_dict['city'], ref_dict['region'], ref_dict['country'], ref_dict['category'], limit*3)
        )
        candidates = cur.fetchall()
        candidate_dicts = [dict(zip([desc[0] for desc in cur.description], row)) for row in candidates]
        similar = []
        ref_keywords = set(ref_dict.get('matched_keywords') or [])
        for cand in candidate_dicts:
            cand_keywords = set(cand.get('matched_keywords') or [])
            overlap = ref_keywords & cand_keywords
            union = ref_keywords | cand_keywords
            score = len(overlap) / max(1, len(union))
            if score >= min_score:
                similar.append({"uuid": cand['uuid'], "score": score})
        similar_sorted = sorted(similar, key=lambda x: x['score'], reverse=True)[:limit]
        cur.close()
        conn.close()
        return [s["uuid"] for s in similar_sorted]
    except Exception as e:
        log.error(f"[db_utils.py] Error in link_similar_alerts: {e}")
        return []