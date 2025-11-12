# db_utils.py — drop-in (Sentinel AI) • v2025-08-23
# Patch 2025-08-25: raw_alerts uses JSON-wrapped tags (jsonb) + persists source_tag/kind/priority
# Postgres helpers for RSS ingest, Threat Engine, and Advisor pipeline.

from __future__ import annotations
import os
import uuid as _uuid
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import atexit
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2 import pool
from psycopg2.extras import execute_values, RealDictCursor, Json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_utils")

# ---------------------------------------------------------------------
# Connection Pool Management
# ---------------------------------------------------------------------

_connection_pool = None

def get_connection_pool():
    """Get or create the global connection pool."""
    global _connection_pool
    if _connection_pool is None:
        from config import CONFIG
        
        if not CONFIG.database.url:
            raise RuntimeError("DATABASE_URL not set")
        try:
            _connection_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=CONFIG.database.pool_min_size,
                maxconn=CONFIG.database.pool_max_size,
                dsn=CONFIG.database.url
            )
            # Register cleanup on exit
            atexit.register(close_connection_pool)
            logger.info("Connection pool initialized (min=%s, max=%s)", 
                       CONFIG.database.pool_min_size, 
                       CONFIG.database.pool_max_size)
        except Exception as e:
            logger.error("Failed to create connection pool: %s", e)
            raise
    return _connection_pool

def close_connection_pool():
    """Close all connections in the pool."""
    global _connection_pool
    if _connection_pool:
        try:
            _connection_pool.closeall()
            logger.info("Connection pool closed")
        except Exception as e:
            logger.error("Error closing connection pool: %s", e)
        finally:
            _connection_pool = None

def _coerce_numeric(value, default, min_val=None, max_val=None):
    """
    Safely coerce to numeric with bounds checking.
    
    Args:
        value: Input value to coerce
        default: Default value if coercion fails or value is None
        min_val: Minimum allowed value (optional)
        max_val: Maximum allowed value (optional)
    
    Returns:
        Numeric value within bounds or default
    """
    try:
        num = float(value) if value is not None else default
        # Handle NaN values by using default
        if num != num:  # NaN check (NaN != NaN is True)
            num = default
        if min_val is not None:
            num = max(min_val, num)
        if max_val is not None:
            num = min(max_val, num)
        return num
    except (ValueError, TypeError):
        return default

def _conn():
    """Get connection from pool."""
    try:
        return get_connection_pool().getconn()
    except Exception as e:
        logger.error("Failed to get connection from pool: %s", e)
        raise

def _release_conn(conn):
    """Return connection to pool."""
    if conn:
        try:
            get_connection_pool().putconn(conn)
        except Exception as e:
            logger.error("Failed to return connection to pool: %s", e)

@contextmanager
def _get_db_connection():
    """Context manager that guarantees connection return and proper transaction handling"""
    conn = _conn()
    try:
        yield conn
        # Only commit if no exceptions occurred
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _release_conn(conn)

# Database operation helpers with guaranteed connection return
def execute(query: str, params: tuple = ()) -> None:
    """Execute a single statement with guaranteed connection return"""
    with _get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)

def fetch_one(query: str, params: tuple = ()):
    """Fetch a single row with guaranteed connection return"""
    with _get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchone()

def fetch_all(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Fetch all rows as dicts with guaranteed connection return"""
    with _get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchall()

def log_security_event(event_type: str, details: str) -> None:
    try:
        logger.warning("[SECURITY_EVENT] %s: %s", event_type, details)
    except Exception:
        pass

# ---------------------------------------------------------------------
# RAW ALERTS (ingest side)
# ---------------------------------------------------------------------

def save_raw_alerts_to_db(alerts: List[Dict[str, Any]]) -> int:
    """
    Bulk upsert raw alerts. Expected fields:
    uuid, title, summary, en_snippet, link, source, published (datetime or iso),
    region, country, city, tags (list[str] or json), language,
    latitude, longitude,
    source_tag, source_kind, source_priority,
    location_method (str), location_confidence (str), location_sharing (bool)
    """
    if not alerts:
        logger.info("No alerts to write.")
        return 0

    cols = [
        "uuid","title","summary","en_snippet","link","source","published",
        "region","country","city","tags","language","ingested_at",
        "latitude","longitude",
        "source_tag","source_kind","source_priority",
        "location_method","location_confidence","location_sharing"
    ]

    def _coerce(a: Dict[str, Any]) -> Tuple:
        aid = a.get("uuid") or str(_uuid.uuid4())
        if isinstance(aid, _uuid.UUID):
            aid = str(aid)

        published = a.get("published")
        if isinstance(published, str):
            try:
                published = datetime.fromisoformat(published.replace("Z","+00:00")).replace(tzinfo=None)
            except Exception:
                published = None

        tags = a.get("tags") or []
        # Ensure Python list/dict, then wrap as JSON for jsonb column
        if isinstance(tags, str):
            import ast
            try:
                tags = ast.literal_eval(tags)
            except Exception:
                tags = [tags]
        # If still not list/dict, coerce minimally
        if not isinstance(tags, (list, dict)):
            tags = [str(tags)]

        # Coerce priority if present
        sp = a.get("source_priority")
        try:
            sp = int(sp) if sp is not None else None
        except Exception:
            sp = None

        # Coerce location_sharing to bool/None
        ls = a.get("location_sharing")
        if isinstance(ls, str):
            ls_str = ls.strip().lower()
            if ls_str in ("true", "1", "yes", "y"):
                ls = True
            elif ls_str in ("false", "0", "no", "n"):
                ls = False
            else:
                ls = None
        elif isinstance(ls, (int, float)):
            try:
                ls = bool(int(ls))
            except Exception:
                ls = None
        elif isinstance(ls, bool):
            pass
        else:
            # leave None or other unexpected types as None
            if ls is not None:
                ls = None

        # Coerce location_confidence to text (not float)
        lc = a.get("location_confidence")
        if lc is not None:
            lc = str(lc)  # Keep as text: "high", "medium", "low", "none"
        
        # Get location_method as text
        lm = a.get("location_method")
        if lm is not None:
            lm = str(lm)  # Keep as text: "ner", "keywords", "llm", "feed_tag", "fuzzy", "none"

        return (
            aid,
            a.get("title"),
            a.get("summary"),
            a.get("en_snippet"),
            a.get("link"),
            a.get("source"),
            published,
            a.get("region"),
            a.get("country"),
            a.get("city"),
            Json(tags),                           # jsonb
            a.get("language") or "en",
            a.get("ingested_at") or datetime.utcnow(),
            _coerce_numeric(a.get("latitude"), None, -90, 90),   # latitude: -90 to 90
            _coerce_numeric(a.get("longitude"), None, -180, 180), # longitude: -180 to 180
            a.get("source_tag"),
            a.get("source_kind"),
            sp,
            lm,  # location_method (text)
            lc,  # location_confidence (text)
            ls,  # location_sharing (boolean)
        )

    rows = [_coerce(a) for a in alerts]

    # Log type of tags for the first row for debugging
    if rows:
        logger.info(
            "Attempting to insert %d rows to raw_alerts. First row tags: %r (type=%r)",
            len(rows), rows[0][10], type(rows[0][10])
        )

    sql = f"""
    INSERT INTO raw_alerts ({", ".join(cols)})
    VALUES %s
    ON CONFLICT (uuid) DO NOTHING
    """
    try:
        with _get_db_connection() as conn:
            with conn.cursor() as cur:
                execute_values(cur, sql, rows)
                logger.info("Insert to raw_alerts completed. Attempted: %d rows", len(rows))
        return len(rows)
    except Exception as e:
        logger.error("DB insert to raw_alerts failed: %s", e)
        return 0

def fetch_raw_alerts_from_db(
    region: Optional[str] = None,
    country: Optional[str] = None,
    city: Optional[str] = None,
    limit: int = 1000
) -> List[Dict[str, Any]]:
    """
    Return recent raw alerts for enrichment.
    """
    where = []
    params: List[Any] = []
    if region:
        where.append("region = %s")
        params.append(region)
    if country:
        where.append("country = %s")
        params.append(country)
    if city:
        where.append("city = %s")
        params.append(city)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    q = f"""
        SELECT uuid, title, summary, en_snippet, link, source, published,
               region, country, city, tags, language, ingested_at,
               latitude, longitude,
               source_tag, source_kind, source_priority
        FROM raw_alerts
        {where_sql}
        ORDER BY published DESC NULLS LAST, ingested_at DESC
        LIMIT %s
    """
    params.append(limit)
    return fetch_all(q, tuple(params))

# ---------------------------------------------------------------------
# ALERTS (enriched) — final schema (Option A)
# ---------------------------------------------------------------------

def save_alerts_to_db(alerts: List[Dict[str, Any]]) -> int:
    """
    Bulk upsert into alerts (final schema Option A).
    """
    from config import CONFIG
    
    if not CONFIG.database.url:
        log_security_event("db_config_error", "DATABASE_URL not set for save_alerts_to_db")
        raise RuntimeError("DATABASE_URL not set")

    if not alerts:
        logger.info("No enriched alerts to write.")
        return 0

    columns = [
        "uuid","title","summary","en_snippet","gpt_summary","link","source","published",
        "region","country","city",
        "category","category_confidence","threat_level","threat_label","score","confidence","reasoning",
        "review_flag","review_notes","ingested_at","model_used","sentiment","forecast","legal_risk","cyber_ot_risk",
        "environmental_epidemic_risk","keyword_weight","tags","trend_score","trend_score_msg","is_anomaly",
        "early_warning_indicators","series_id","incident_series","historical_context",
        "subcategory","domains","incident_count_30d","recent_count_7d","baseline_avg_7d",
        "baseline_ratio","trend_direction","anomaly_flag","future_risk_probability",
        "reports_analyzed","sources","cluster_id",
        "latitude","longitude","location_method","location_confidence","location_sharing",
        "embedding"
    ]

    def _json(v):
        return Json(v) if v is not None else None

    def _coerce_row(a: Dict[str, Any]) -> Tuple:
        aid = a.get("uuid") or str(_uuid.uuid4())
        if isinstance(aid, _uuid.UUID):
            aid = str(aid)

        published = a.get("published")
        if isinstance(published, str):
            try:
                published = datetime.fromisoformat(published.replace("Z","+00:00")).replace(tzinfo=None)
            except Exception:
                published = None

        ingested_at = a.get("ingested_at") or datetime.utcnow()

        tags    = a.get("tags") or []
        if isinstance(tags, str):
            import ast
            try:
                tags = ast.literal_eval(tags)
                if not isinstance(tags, list):
                    tags = [str(tags)]
            except Exception:
                tags = [str(tags)]
        elif not isinstance(tags, list):
            tags = [str(tags)]

        ewi     = a.get("early_warning_indicators") or []
        domains = a.get("domains") or []
        sources = a.get("sources") or []

        is_anomaly   = bool(a.get("is_anomaly") or a.get("anomaly_flag") or False)
        anomaly_flag = bool(a.get("anomaly_flag") or False)

        # Safe defaults with numeric coercion
        incident_count_30d = _coerce_numeric(a.get("incident_count_30d"), 0, 0, None)
        recent_count_7d    = _coerce_numeric(a.get("recent_count_7d"), 0, 0, None)
        baseline_avg_7d    = _coerce_numeric(a.get("baseline_avg_7d"), 0, 0, None)

        baseline_ratio = _coerce_numeric(a.get("baseline_ratio"), 1.0, 0, None)
        trend_direction = a.get("trend_direction") or "stable"
        
        # Handle pgvector-compatible embedding data
        embedding = a.get("embedding")
        pgvector_embedding = None
        
        if embedding and isinstance(embedding, list):
            # Convert to PostgreSQL REAL[] array format
            # Ensure exactly 1536 dimensions for OpenAI embeddings
            if len(embedding) == 1536:
                pgvector_embedding = embedding  # Will be handled by psycopg2 as array
            else:
                # Pad or truncate to 1536 dimensions
                if len(embedding) < 1536:
                    pgvector_embedding = embedding + [0.0] * (1536 - len(embedding))
                else:
                    pgvector_embedding = embedding[:1536]

        return (
            aid,
            a.get("title"),
            a.get("summary"),
            a.get("en_snippet"),
            a.get("gpt_summary"),
            a.get("link"),
            a.get("source"),
            published,
            a.get("region"),
            a.get("country"),
            a.get("city"),
            a.get("category") or a.get("type"),
            _coerce_numeric(a.get("category_confidence") or a.get("type_confidence"), 0.5, 0, 1),
            a.get("threat_level") or a.get("label"),
            a.get("threat_label") or a.get("label"),
            _coerce_numeric(a.get("score"), 0, 0, 100),  # score: 0-100
            _coerce_numeric(a.get("confidence"), 0.5, 0, 1),  # confidence: 0-1
            a.get("reasoning"),
            a.get("review_flag"),
            a.get("review_notes"),
            ingested_at,
            a.get("model_used"),
            a.get("sentiment"),
            a.get("forecast"),
            a.get("legal_risk"),
            a.get("cyber_ot_risk"),
            a.get("environmental_epidemic_risk"),
            _coerce_numeric(a.get("keyword_weight"), 0, 0, None),
            tags,                 # alerts.tags is text[]
            _coerce_numeric(a.get("trend_score"), 0, 0, 100),
            a.get("trend_score_msg"),
            bool(is_anomaly),
            ewi,                  # text[]
            a.get("series_id"),
            a.get("incident_series"),
            a.get("historical_context"),
            a.get("subcategory"),
            _json(domains),       # jsonb
            incident_count_30d,
            recent_count_7d,
            baseline_avg_7d,
            baseline_ratio,
            trend_direction,
            bool(anomaly_flag),
            _coerce_numeric(a.get("future_risk_probability"), 0.25, 0, 1),  # probability: 0-1
            a.get("reports_analyzed"),
            _json(sources),       # jsonb
            a.get("cluster_id"),
            _coerce_numeric(a.get("latitude"), None, -90, 90),   # latitude: -90 to 90
            _coerce_numeric(a.get("longitude"), None, -180, 180), # longitude: -180 to 180
            a.get("location_method") or "unknown",
            a.get("location_confidence") or "medium", 
            bool(a.get("location_sharing", True)),
            pgvector_embedding,   # REAL[1536] pgvector-compatible array
        )

    rows = [_coerce_row(a) for a in alerts]

    if rows:
        logger.info(
            "Attempting to insert %d rows to alerts. First row tags: %r (type=%r)",
            len(rows), rows[0][28], type(rows[0][28])
        )

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
        category = EXCLUDED.category,
        category_confidence = EXCLUDED.category_confidence,
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
        subcategory = EXCLUDED.subcategory,
        domains = EXCLUDED.domains,
        incident_count_30d = EXCLUDED.incident_count_30d,
        recent_count_7d = EXCLUDED.recent_count_7d,
        baseline_avg_7d = EXCLUDED.baseline_avg_7d,
        baseline_ratio = EXCLUDED.baseline_ratio,
        trend_direction = EXCLUDED.trend_direction,
        anomaly_flag = EXCLUDED.anomaly_flag,
        future_risk_probability = EXCLUDED.future_risk_probability,
        reports_analyzed = EXCLUDED.reports_analyzed,
        sources = EXCLUDED.sources,
        cluster_id = EXCLUDED.cluster_id,
        latitude = EXCLUDED.latitude,
        longitude = EXCLUDED.longitude,
        location_method = EXCLUDED.location_method,
        location_confidence = EXCLUDED.location_confidence,
        location_sharing = EXCLUDED.location_sharing,
        embedding = EXCLUDED.embedding
    """
    try:
        with _get_db_connection() as conn:
            with conn.cursor() as cur:
                execute_values(cur, sql, rows)
                logger.info("Insert to alerts completed. Attempted: %d rows", len(rows))
        return len(rows)
    except Exception as e:
        logger.error("DB insert to alerts failed: %s", e)
        return 0

# ---------- Alerts fetch for Advisor/Chat ----------
def fetch_alerts_from_db(
    region: Optional[str] = None,
    country: Optional[str] = None,
    city: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Pull recent enriched alerts (Option A schema).
    Filters:
      - region: matches any of region/city/country
      - country, city: exact
      - category: alerts.category (NOT threat_level)
    """
    where = []
    params: List[Any] = []

    if region:
        where.append("(region = %s OR city = %s OR country = %s)")
        params.extend([region, region, region])
    if country:
        where.append("country = %s")
        params.append(country)
    if city:
        where.append("city = %s")
        params.append(city)
    if category:
        where.append("category = %s")
        params.append(category)

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    q = f"""
      SELECT uuid, title, summary, gpt_summary, link, source, published,
             region, country, city, category, subcategory,
             threat_level, threat_label, score, confidence, reasoning,
             sentiment, forecast, legal_risk, cyber_ot_risk, environmental_epidemic_risk,
             tags, trend_score, trend_score_msg, trend_direction, is_anomaly, anomaly_flag,
             early_warning_indicators, series_id, incident_series, historical_context,
             domains, incident_count_30d, recent_count_7d, baseline_avg_7d,
             baseline_ratio, future_risk_probability, reports_analyzed, sources, cluster_id,
             latitude, longitude, location_method, location_confidence, location_sharing
      FROM alerts
      {where_sql}
      ORDER BY published DESC NULLS LAST
      LIMIT %s
    """
    params.append(limit)
    with _get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(q, tuple(params))
            rows = cur.fetchall()
            # Supply safe defaults for missing keys
            for r in rows:
                if r.get("incident_count_30d") is None:
                    r["incident_count_30d"] = 0
                if r.get("recent_count_7d") is None:
                    r["recent_count_7d"] = 0
                if r.get("baseline_avg_7d") is None:
                    r["baseline_avg_7d"] = 0
                if r.get("baseline_ratio") is None:
                    r["baseline_ratio"] = 1.0
                if r.get("trend_direction") is None:
                    r["trend_direction"] = "stable"
            return rows

def fetch_alerts_from_db_strict_geo(
    region: Optional[str] = None,
    country: Optional[str] = None,
    city: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Enhanced version with strict geographic filtering to prevent cross-contamination.
    Only returns alerts where the primary location fields match the query.
    """
    where = []
    params: List[Any] = []

    # Build WHERE conditions with priority logic
    # When country and city are specified, prioritize them over region
    if country and city:
        where.append("country ILIKE %s AND city ILIKE %s")
        params.extend([f"%{country}%", f"%{city}%"])
    elif country:
        where.append("country ILIKE %s")
        params.append(f"%{country}%")
    elif region:
        # More precise matching - check if it's a country name first
        where.append("(country ILIKE %s OR (region ILIKE %s AND country IS NOT NULL))")
        params.extend([f"%{region}%", f"%{region}%"])
    elif city:
        where.append("city ILIKE %s")
        params.append(f"%{city}%")
    
    if category:
        where.append("category = %s")
        params.append(category)

    # Add relevance filter to exclude obvious sports/entertainment
    # ✅ SAFE: Proper parameterized query construction
    sports_terms = ['football', 'soccer', 'champion', 'award', 'hat-trick', 'hatrrick', 'UCL', 'europa']
    for term in sports_terms:
        where.append("title NOT ILIKE %s")
        params.append(f"%{term}%")

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    # Optimized query - select only essential fields for faster chat responses
    q = f"""
      SELECT uuid, title, summary, gpt_summary, link, source, published,
             region, country, city, category, threat_level, threat_label, 
             score, confidence, reasoning, sentiment, forecast, 
             legal_risk, cyber_ot_risk, environmental_epidemic_risk,
             incident_count_30d, trend_direction, 
             latitude, longitude, location_confidence
      FROM alerts
      {where_sql}
      ORDER BY published DESC NULLS LAST
      LIMIT %s
    """
    params.append(limit)
    
    with _get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(q, tuple(params))
            rows = cur.fetchall()
            
            # Supply safe defaults for missing keys
            for r in rows:
                if r.get("incident_count_30d") is None:
                    r["incident_count_30d"] = 0
                if r.get("recent_count_7d") is None:
                    r["recent_count_7d"] = 0
                if r.get("baseline_avg_7d") is None:
                    r["baseline_avg_7d"] = 0
                if r.get("baseline_ratio") is None:
                    r["baseline_ratio"] = 1.0
                if r.get("trend_direction") is None:
                    r["trend_direction"] = "stable"
                    
            # Enhanced post-query geographic relevance filtering
            if (region or country or city) and rows:
                filtered_rows = []
                
                for row in rows:
                    row_country = (row.get("country") or "").lower()
                    row_city = (row.get("city") or "").lower()
                    row_region = (row.get("region") or "").lower()
                    row_source = (row.get("source") or "").lower()
                    
                    is_relevant = False
                    
                    # Exact country match has highest priority
                    if country and country.lower() in row_country:
                        is_relevant = True
                    
                    # City match (if specified)
                    elif city and city.lower() in row_city:
                        is_relevant = True
                    
                    # Region-based matching (fallback)
                    elif region:
                        region_lower = region.lower()
                        is_relevant = (
                            region_lower in row_country or
                            region_lower in row_city or
                            region_lower in row_region or
                            # Source geography check (e.g., Nigerian source for Nigeria query)
                            (region_lower in row_source and row_country and region_lower in row_country)
                        )
                    
                    # If no geographic filters specified, include all
                    elif not region and not country and not city:
                        is_relevant = True
                    
                    if is_relevant:
                        filtered_rows.append(row)
                
                # Log filtering results for debugging
                if len(filtered_rows) != len(rows):
                    logger.info(f"Geographic filtering: {len(rows)} → {len(filtered_rows)} alerts (region={region}, country={country}, city={city})")
                        
                return filtered_rows
                    
            return rows

# ---------------------------------------------------------------------
# User profile helpers (for chat/advisor and /profile endpoints)
# ---------------------------------------------------------------------

def fetch_user_profile(email: str) -> Dict[str, Any]:
    """
    Return merged profile from users + optional user_profiles.profile_json.
    Matches what chat_handler expects.
    """
    try:
        row = fetch_one(
            "SELECT email, plan, name, employer, email_verified, "
            "preferred_region, preferred_threat_type, home_location, extra_details "
            "FROM users WHERE email=%s",
            (email,),
        )
        if not row:
            return {}

        data: Dict[str, Any] = {
            "email": row[0],
            "plan": row[1],
            "name": row[2],
            "employer": row[3],
            "email_verified": bool(row[4]),
            "preferred_region": row[5],
            "preferred_threat_type": row[6],
            "home_location": row[7],
            "extra_details": row[8] or {},
        }

        # Optional extended JSON profile
        try:
            pr = fetch_one("SELECT profile_json FROM user_profiles WHERE email=%s", (email,))
            if pr and pr[0]:
                data["profile"] = pr[0]
        except Exception:
            pass

        return data
    except Exception as e:
        logger.error("fetch_user_profile error: %s", e)
        return {}

# ---------------------------------------------------------------------
# Historical pulls for Threat Engine / Scoring
# ---------------------------------------------------------------------

def fetch_past_incidents(
    region: Optional[str] = None,
    category: Optional[str] = None,
    days: int = 7,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Pulls recent incidents from alerts for a given region/city/country and/or category.
    Returns dict rows (score, published, etc.) used by scorer/engine.
    """
    where = ["published >= NOW() - INTERVAL %s"]
    params: List[Any] = [f"{max(days,1)} days"]

    # Region filter: allow region OR city OR country
    if region:
        where.append("(region = %s OR city = %s OR country = %s)")
        params.extend([region, region, region])
    if category:
        where.append("category = %s")
        params.append(category)

    where_sql = "WHERE " + " AND ".join(where) if where else ""
    q = f"""
        SELECT uuid, title, summary, score, published, category, subcategory,
               city, country, region, threat_level, threat_label, tags,
               latitude, longitude
        FROM alerts
        {where_sql}
        ORDER BY published DESC
        LIMIT %s
    """
    params.append(limit)
    return fetch_all(q, tuple(params))

# ---------------------------------------------------------------------
# Region trend (optional helper; safe if table missing)
# ---------------------------------------------------------------------

def save_region_trend(
    region: Optional[str],
    city: Optional[str],
    trend_window_start: datetime,
    trend_window_end: datetime,
    incident_count: int,
    categories: Optional[List[str]] = None
) -> None:
    """
    Upsert region trend metrics. If the table doesn't exist, we log and continue.
    Expected table (suggested):
      CREATE TABLE IF NOT EXISTS region_trends (
        region text,
        city text,
        window_start timestamp,
        window_end timestamp,
        incident_count int,
        categories text[],
        updated_at timestamp default now(),
        PRIMARY KEY (region, city, window_start, window_end)
      );
    """
    try:
        sql = """
        INSERT INTO region_trends (region, city, window_start, window_end, incident_count, categories, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,NOW())
        ON CONFLICT (region, city, window_start, window_end) DO UPDATE SET
            incident_count = EXCLUDED.incident_count,
            categories = EXCLUDED.categories,
            updated_at = NOW()
        """
        execute(sql, (
            region, city, trend_window_start, trend_window_end, 
            _coerce_numeric(incident_count, 0, 0, None), categories or []
        ))
    except Exception as e:
        logger.info("save_region_trend skipped (table may not exist): %s", e)

# ---------------------------------------------------------------------
# Standalone Embedding Functions
# ---------------------------------------------------------------------

def store_alert_embedding(alert_uuid: str, embedding: List[float]) -> bool:
    """
    Store embedding for a single alert using the current REAL[1536] vector system.
    
    Args:
        alert_uuid: UUID of the alert to store embedding for
        embedding: Embedding vector (list of 1536 floats)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Validate embedding format
        if not embedding or not isinstance(embedding, list):
            logger.warning(f"Invalid embedding format for alert {alert_uuid}")
            return False
            
        # Ensure exactly 1536 dimensions for OpenAI embeddings
        pgvector_embedding = None
        if len(embedding) == 1536:
            pgvector_embedding = embedding
        elif len(embedding) < 1536:
            # Pad with zeros if too short
            pgvector_embedding = embedding + [0.0] * (1536 - len(embedding))
        else:
            # Truncate if too long
            pgvector_embedding = embedding[:1536]
            
        # Update the alert with the embedding
        query = """
            UPDATE alerts 
            SET embedding = %s 
            WHERE uuid = %s
        """
        
        result = execute(query, (pgvector_embedding, alert_uuid))
        return result is not None
        
    except Exception as e:
        logger.error(f"Error storing embedding for alert {alert_uuid}: {e}")
        return False


def upsert_alert_embedding(alert_uuid: str, embedding: List[float]) -> bool:
    """
    Upsert embedding for an alert (insert alert if it doesn't exist).
    
    Args:
        alert_uuid: UUID of the alert
        embedding: Embedding vector (list of 1536 floats)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Validate embedding format  
        if not embedding or not isinstance(embedding, list):
            logger.warning(f"Invalid embedding format for alert {alert_uuid}")
            return False
            
        # Ensure exactly 1536 dimensions
        pgvector_embedding = None
        if len(embedding) == 1536:
            pgvector_embedding = embedding
        elif len(embedding) < 1536:
            pgvector_embedding = embedding + [0.0] * (1536 - len(embedding))
        else:
            pgvector_embedding = embedding[:1536]
            
        # Insert or update with embedding
        query = """
            INSERT INTO alerts (uuid, embedding, created_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (uuid) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                updated_at = NOW()
        """
        
        result = execute(query, (alert_uuid, pgvector_embedding))
        return result is not None
        
    except Exception as e:
        logger.error(f"Error upserting embedding for alert {alert_uuid}: {e}")
        return False


def get_alert_embedding(alert_uuid: str) -> Optional[List[float]]:
    """
    Retrieve embedding for a specific alert.
    
    Args:
        alert_uuid: UUID of the alert
        
    Returns:
        Embedding vector as list of floats, or None if not found
    """
    try:
        query = """
            SELECT embedding 
            FROM alerts 
            WHERE uuid = %s AND embedding IS NOT NULL
        """
        
        result = fetch_one(query, (alert_uuid,))
        if result and result[0]:
            return list(result[0])  # Convert array to list
        return None
        
    except Exception as e:
        logger.error(f"Error retrieving embedding for alert {alert_uuid}: {e}")
        return None
