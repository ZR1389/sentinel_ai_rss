# db_utils.py — drop-in (Sentinel AI) • v2025-08-23
# Patch 2025-08-25: raw_alerts uses JSON-wrapped tags (jsonb) + persists source_tag/kind/priority
# Postgres helpers for RSS ingest, Threat Engine, and Advisor pipeline.

from __future__ import annotations
import os
import uuid as _uuid
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras
from psycopg2.extras import execute_values, RealDictCursor, Json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_utils")

# ---------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------

def get_db_url() -> Optional[str]:
    return os.getenv("DATABASE_URL")

def _conn():
    db_url = get_db_url()
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg2.connect(db_url)

# Simple helpers used by RSS health/backoff and misc queries
def execute(query: str, params: tuple = ()) -> None:
    """Execute a single statement (no return)."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(query, params)

def fetch_one(query: str, params: tuple = ()):
    """Fetch a single row (tuple) or None."""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()

def fetch_all(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Fetch all rows as dicts."""
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
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
            a.get("latitude"),
            a.get("longitude"),
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
        with _conn() as conn, conn.cursor() as cur:
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
    db_url = get_db_url()
    if not db_url:
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
        "latitude","longitude","location_method","location_confidence","location_sharing"
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

        # Safe defaults
        incident_count_30d = a.get("incident_count_30d", 0) or 0
        recent_count_7d    = a.get("recent_count_7d", 0) or 0
        baseline_avg_7d    = a.get("baseline_avg_7d", 0) or 0

        baseline_ratio = a.get("baseline_ratio")
        if baseline_ratio is None:
            baseline_ratio = 1.0

        trend_direction = a.get("trend_direction") or "stable"

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
            a.get("category_confidence") or a.get("type_confidence"),
            a.get("threat_level") or a.get("label"),
            a.get("threat_label") or a.get("label"),
            a.get("score"),
            a.get("confidence"),
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
            a.get("keyword_weight"),
            tags,                 # alerts.tags is text[]
            a.get("trend_score"),
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
            a.get("future_risk_probability"),
            a.get("reports_analyzed"),
            _json(sources),       # jsonb
            a.get("cluster_id"),
            a.get("latitude"),
            a.get("longitude"),
            a.get("location_method") or "unknown",
            a.get("location_confidence") or "medium", 
            bool(a.get("location_sharing", True)),
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
        location_sharing = EXCLUDED.location_sharing
    """
    try:
        with _conn() as conn, conn.cursor() as cur:
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
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
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

    if region:
        # More precise matching - check if it's a country name first
        where.append("(country ILIKE %s OR (region ILIKE %s AND country IS NOT NULL))")
        params.extend([f"%{region}%", f"%{region}%"])
    if country:
        where.append("country ILIKE %s")
        params.append(f"%{country}%")
    if city:
        where.append("city ILIKE %s")
        params.append(f"%{city}%")
    if category:
        where.append("category = %s")
        params.append(category)

    # Add relevance filter to exclude obvious sports/entertainment
    where.append("(title NOT ILIKE %s AND title NOT ILIKE %s AND title NOT ILIKE %s AND title NOT ILIKE %s AND title NOT ILIKE %s AND title NOT ILIKE %s AND title NOT ILIKE %s AND title NOT ILIKE %s)")
    params.extend(['%football%', '%soccer%', '%champion%', '%award%', '%hat-trick%', '%hatrrick%', '%UCL%', '%europa%'])

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
    
    with _conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
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
                
        # Filter out geographically irrelevant results post-query
        if region and rows:
            filtered_rows = []
            region_lower = region.lower()
            for row in rows:
                country = (row.get("country") or "").lower()
                city = (row.get("city") or "").lower()
                source = (row.get("source") or "").lower()
                
                # Check if the alert is actually about the requested region
                is_relevant = (
                    region_lower in country or
                    region_lower in city or
                    (region_lower in source and country and region_lower in country)
                )
                
                if is_relevant:
                    filtered_rows.append(row)
                    
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
            region, city, trend_window_start, trend_window_end, int(incident_count), categories or []
        ))
    except Exception as e:
        logger.info("save_region_trend skipped (table may not exist): %s", e)
