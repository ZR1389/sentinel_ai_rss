import os
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime
import uuid
import logging

# --- Logging configuration ---
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

def save_alerts_to_db(alerts):
    """
    Insert or upsert a list of alert dicts into the alerts table.
    Each alert must have at least a 'uuid' field. If not present, a new UUID will be generated.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        log.error("DATABASE_URL not set in environment")
        raise Exception("DATABASE_URL not set in environment")
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        log.error(f"Could not connect to DB: {e}")
        raise
    cur = conn.cursor()

    columns = [
        "uuid", "title", "summary", "en_snippet", "gpt_summary", "link", "source", "published",
        "region", "country", "city", "type", "type_confidence", "threat_level", "threat_label",
        "score", "confidence", "reasoning", "review_flag", "review_notes", "ingested_at",
        "model_used", "sentiment", "forecast", "legal_risk", "cyber_ot_risk",
        "environmental_epidemic_risk", "keyword_weight", "tags"
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
        # Accept string list (e.g. '["foo","bar"]') and convert to list
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
        tags = EXCLUDED.tags
    ;
    """
    try:
        execute_values(cur, sql, values)
        conn.commit()
        log.info(f"Inserted/updated {len(values)} alerts.")
    except Exception as e:
        conn.rollback()
        log.error(f"Error in save_alerts_to_db: {e}")
        raise
    finally:
        cur.close()
        conn.close()

def fetch_alerts_from_db(
    region=None, country=None, city=None, threat_level=None, threat_label=None,
    start_time=None, end_time=None, limit=100
):
    """
    Fetch alerts from the DB, filtered by optional parameters.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        log.error("DATABASE_URL not set in environment")
        raise Exception("DATABASE_URL not set in environment")
    try:
        conn = psycopg2.connect(db_url)
    except Exception as e:
        log.error(f"Could not connect to DB: {e}")
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

    base_sql += " ORDER BY published DESC NULLS LAST LIMIT %s"
    params.append(limit)

    try:
        cur.execute(base_sql, params)
        rows = cur.fetchall()
        colnames = [desc[0] for desc in cur.description]
        results = [dict(zip(colnames, row)) for row in rows]
        log.info(f"Fetched {len(results)} alerts from DB.")
    except Exception as e:
        log.error(f"[db_utils.py] Error in fetch_alerts_from_db: {e}")
        raise
    finally:
        cur.close()
        conn.close()
    return results