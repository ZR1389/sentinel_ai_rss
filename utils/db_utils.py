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
        # Try centralized config first, fallback to direct env for cron jobs
        try:
            from core.config import CONFIG
            database_url = CONFIG.database.url
            min_size = CONFIG.database.pool_min_size
            max_size = CONFIG.database.pool_max_size
        except (ImportError, AttributeError):
            # Fallback for Railway cron jobs that can't load CONFIG
            database_url = os.getenv("DATABASE_URL")
            min_size = int(os.getenv("DB_POOL_MIN_SIZE", "1"))
            max_size = int(os.getenv("DB_POOL_MAX_SIZE", "20"))
        
        if not database_url:
            raise RuntimeError("DATABASE_URL not set")
        try:
            _connection_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=min_size,
                maxconn=max_size,
                dsn=database_url
            )
            # Register cleanup on exit
            atexit.register(close_connection_pool)
            logger.info("Connection pool initialized (min=%s, max=%s)", 
                       min_size, max_size)
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

# Enhanced database operation helpers with comprehensive logging and performance monitoring
import time
import hashlib
from functools import wraps
from typing import Union

# Database performance monitoring
_query_stats = {}
_slow_query_threshold = 1.0  # Log queries taking longer than 1 second

def _log_query_performance(query: str, params: tuple, duration: float, row_count: int = None):
    """Log database query performance metrics"""
    # Create query signature for tracking
    query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
    query_type = query.strip().split()[0].upper()
    
    # Track query statistics
    if query_hash not in _query_stats:
        _query_stats[query_hash] = {
            'query_type': query_type,
            'total_calls': 0,
            'total_duration': 0,
            'avg_duration': 0,
            'max_duration': 0,
            'min_duration': float('inf'),
            'slow_queries': 0
        }
    
    stats = _query_stats[query_hash]
    stats['total_calls'] += 1
    stats['total_duration'] += duration
    stats['avg_duration'] = stats['total_duration'] / stats['total_calls']
    stats['max_duration'] = max(stats['max_duration'], duration)
    stats['min_duration'] = min(stats['min_duration'], duration)
    
    if duration > _slow_query_threshold:
        stats['slow_queries'] += 1
        logger.warning(
            f"[SLOW_QUERY] {query_type} took {duration:.3f}s (hash: {query_hash}) "
            f"- rows: {row_count if row_count is not None else 'N/A'}"
        )
        logger.debug(f"[SLOW_QUERY_DETAILS] Query: {query[:200]}...")
        logger.debug(f"[SLOW_QUERY_PARAMS] Params: {params}")
    
    # Log detailed performance info for debugging
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            f"[DB_PERF] {query_type} {query_hash} - "
            f"duration: {duration:.3f}s, rows: {row_count if row_count is not None else 'N/A'}, "
            f"avg: {stats['avg_duration']:.3f}s, calls: {stats['total_calls']}"
        )

def _sanitize_query_for_log(query: str, max_length: int = 150) -> str:
    """Sanitize query for logging (remove sensitive data, truncate)"""
    # Remove common sensitive patterns
    import re
    sanitized = query
    
    # Replace potential sensitive values in common patterns
    sanitized = re.sub(r'(password|token|key)\s*=\s*[\'"][^\'\"]+[\'"]', r'\1=***', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'(password|token|key)\s*=\s*\%s', r'\1=%s', sanitized, flags=re.IGNORECASE)
    
    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length] + "..."
    
    return sanitized

def _log_db_operation(operation_type: str, query: str, params: tuple, duration: float = None, row_count: int = None, error: Exception = None):
    """Comprehensive database operation logging"""
    sanitized_query = _sanitize_query_for_log(query)
    
    if error:
        logger.error(
            f"[DB_ERROR] {operation_type} failed - Query: {sanitized_query} "
            f"- Error: {error}"
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"[DB_ERROR_PARAMS] Params: {params}")
    else:
        if duration is not None:
            logger.info(
                f"[DB_SUCCESS] {operation_type} completed in {duration:.3f}s - "
                f"Query: {sanitized_query}"
                f"{f' - Rows: {row_count}' if row_count is not None else ''}"
            )
        else:
            logger.info(f"[DB_SUCCESS] {operation_type} - Query: {sanitized_query}")
        
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"[DB_PARAMS] Params: {params}")

def execute(query: str, params: tuple = ()) -> None:
    """
    Execute a single statement with comprehensive logging and performance monitoring
    
    Args:
        query: SQL query to execute
        params: Query parameters (tuple)
        
    Raises:
        Exception: Database execution errors
    """
    start_time = time.time()
    error = None
    
    try:
        with _get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                
        # Log successful execution
        duration = time.time() - start_time
        _log_db_operation("EXECUTE", query, params, duration)
        _log_query_performance(query, params, duration)
        
    except Exception as e:
        duration = time.time() - start_time
        error = e
        _log_db_operation("EXECUTE", query, params, duration, error=error)
        raise

def fetch_one(query: str, params: tuple = ()):
    """
    Fetch a single row with comprehensive logging and performance monitoring
    
    Args:
        query: SQL query to execute
        params: Query parameters (tuple)
        
    Returns:
        Single row result or None
        
    Raises:
        Exception: Database query errors
    """
    start_time = time.time()
    error = None
    result = None
    
    try:
        with _get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                result = cur.fetchone()
                
        # Log successful fetch
        duration = time.time() - start_time
        row_count = 1 if result is not None else 0
        _log_db_operation("FETCH_ONE", query, params, duration, row_count)
        _log_query_performance(query, params, duration, row_count)
        
        return result
        
    except Exception as e:
        duration = time.time() - start_time
        error = e
        _log_db_operation("FETCH_ONE", query, params, duration, error=error)
        raise

def fetch_all(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """
    Fetch all rows as dicts with comprehensive logging and performance monitoring
    
    Args:
        query: SQL query to execute
        params: Query parameters (tuple)
        
    Returns:
        List of dictionary rows
        
    Raises:
        Exception: Database query errors
    """
    start_time = time.time()
    error = None
    result = []
    
    try:
        with _get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(query, params)
                result = cur.fetchall()
                
        # Log successful fetch
        duration = time.time() - start_time
        row_count = len(result)
        _log_db_operation("FETCH_ALL", query, params, duration, row_count)
        _log_query_performance(query, params, duration, row_count)
        
        return result
        
    except Exception as e:
        duration = time.time() - start_time
        error = e
        _log_db_operation("FETCH_ALL", query, params, duration, error=error)
        raise

def execute_batch(query: str, params_list: List[tuple]) -> int:
    """
    Execute batch operations with comprehensive logging
    
    Args:
        query: SQL query to execute
        params_list: List of parameter tuples for batch execution
        
    Returns:
        Number of affected rows
        
    Raises:
        Exception: Database execution errors
    """
    if not params_list:
        logger.warning("[DB_BATCH] No parameters provided for batch execution")
        return 0
    
    start_time = time.time()
    error = None
    affected_rows = 0
    
    try:
        with _get_db_connection() as conn:
            with conn.cursor() as cur:
                # Use execute_batch for better performance
                from psycopg2.extras import execute_batch
                execute_batch(cur, query, params_list, page_size=1000)
                affected_rows = len(params_list)
                
        # Log successful batch execution
        duration = time.time() - start_time
        _log_db_operation("EXECUTE_BATCH", query, (f"{len(params_list)} batches",), duration, affected_rows)
        _log_query_performance(query, (f"{len(params_list)} batches",), duration, affected_rows)
        
        return affected_rows
        
    except Exception as e:
        duration = time.time() - start_time
        error = e
        _log_db_operation("EXECUTE_BATCH", query, (f"{len(params_list)} batches",), duration, error=error)
        raise

def get_query_performance_stats() -> Dict[str, Any]:
    """
    Get comprehensive database query performance statistics
    
    Returns:
        Dictionary containing query performance metrics
    """
    total_calls = sum(stats['total_calls'] for stats in _query_stats.values())
    total_duration = sum(stats['total_duration'] for stats in _query_stats.values())
    total_slow_queries = sum(stats['slow_queries'] for stats in _query_stats.values())
    
    return {
        'summary': {
            'total_queries': total_calls,
            'total_duration': total_duration,
            'average_duration': total_duration / total_calls if total_calls > 0 else 0,
            'slow_queries': total_slow_queries,
            'slow_query_percentage': (total_slow_queries / total_calls * 100) if total_calls > 0 else 0,
            'query_types': len(_query_stats)
        },
        'detailed_stats': _query_stats,
        'top_slow_queries': sorted(
            _query_stats.items(),
            key=lambda x: x[1]['slow_queries'],
            reverse=True
        )[:10]
    }

def log_database_performance_summary():
    """Log a comprehensive database performance summary"""
    stats = get_query_performance_stats()
    summary = stats['summary']
    
    logger.info("=" * 80)
    logger.info("📊 DATABASE PERFORMANCE SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total Queries: {summary['total_queries']:,}")
    logger.info(f"Total Duration: {summary['total_duration']:.2f}s")
    logger.info(f"Average Duration: {summary['average_duration']:.3f}s")
    logger.info(f"Slow Queries: {summary['slow_queries']} ({summary['slow_query_percentage']:.1f}%)")
    logger.info(f"Unique Query Types: {summary['query_types']}")
    
    # Log top slow queries
    if stats['top_slow_queries']:
        logger.info(f"\n🐌 Top Slow Query Types:")
        for query_hash, query_stats in stats['top_slow_queries'][:5]:
            if query_stats['slow_queries'] > 0:
                logger.info(
                    f"  {query_stats['query_type']} (Hash: {query_hash}) - "
                    f"{query_stats['slow_queries']} slow queries, "
                    f"avg: {query_stats['avg_duration']:.3f}s, "
                    f"max: {query_stats['max_duration']:.3f}s"
                )
    
    logger.info("=" * 80)

def reset_query_performance_stats():
    """Reset query performance statistics"""
    global _query_stats
    _query_stats = {}
    logger.info("[DB_PERF] Query performance statistics reset")

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

# Allowed languages for processing (English and Arabic for Middle East coverage)
ALLOWED_LANGUAGES = {'en', 'English', '', None}

def fetch_raw_alerts_from_db(
    region: Optional[str] = None,
    country: Optional[str] = None,
    city: Optional[str] = None,
    limit: int = 1000,
    english_only: bool = True
) -> List[Dict[str, Any]]:
    """
    Return recent raw alerts for enrichment.
    
    Args:
        english_only: If True, filter to English content only (default True)
    """
    where = []
    params: List[Any] = []
    
    # Filter to English only by default
    if english_only:
        where.append("(language IS NULL OR language = '' OR language = 'en' OR language = 'English')")
    
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
    # Try centralized config first, fallback to direct env for cron jobs
    try:
        from core.config import CONFIG
        database_url = CONFIG.database.url
    except (ImportError, AttributeError):
        # Fallback for Railway cron jobs
        database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        log_security_event("db_config_error", "DATABASE_URL not set for save_alerts_to_db")
        raise RuntimeError("DATABASE_URL not set")

    if not alerts:
        logger.info("No enriched alerts to write.")
        return 0
    
    # VALIDATION: Reject alerts without proper country (prevents wrong location data)
    valid_alerts = []
    rejected_count = 0
    for alert in alerts:
        country = alert.get("country")
        if not country or not country.strip():
            rejected_count += 1
            logger.warning(f"Rejected alert without country: {alert.get('title', 'NO_TITLE')[:50]} (city={alert.get('city')})")
            continue
        valid_alerts.append(alert)
    
    if rejected_count > 0:
        logger.warning(f"Rejected {rejected_count}/{len(alerts)} alerts due to missing country field")
    
    if not valid_alerts:
        logger.info("No valid alerts to write after country validation.")
        return 0
    
    alerts = valid_alerts  # Use only validated alerts

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
        "source_kind","source_tag","threat_score_components",
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
            a.get("source_kind") or ('intelligence' if str(aid).startswith('acled:') else 'rss'),
            a.get("source_tag") or '',
            _json(a.get("threat_score_components")),  # JSONB
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
        source_kind = EXCLUDED.source_kind,
        source_tag = EXCLUDED.source_tag,
        threat_score_components = EXCLUDED.threat_score_components,
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

def fetch_alerts_by_location_fuzzy(
    city: Optional[str] = None,
    country: Optional[str] = None,
    region: Optional[str] = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """
    Fuzzy location query for alerts when exact matching returns no results.
    Strategy:
      - If country provided, try pycountry fuzzy to normalize
      - If city provided, try city_utils.fuzzy_match_city for canonical form
      - Use ILIKE with wildcards for broader match on city/country
    """
    try:
        # Optional helpers
        try:
            import pycountry  # type: ignore
        except Exception:
            pycountry = None  # type: ignore
        try:
            from utils.city_utils import fuzzy_match_city as _fuzzy_city
        except Exception:
            _fuzzy_city = None  # type: ignore

        norm_country = country
        if country and pycountry is not None:
            try:
                m = pycountry.countries.search_fuzzy(country)
                if m:
                    norm_country = m[0].name
            except Exception:
                pass

        norm_city = city
        if city and _fuzzy_city is not None:
            try:
                cand = _fuzzy_city(city)
                if cand:
                    norm_city = cand
            except Exception:
                pass

        where = []
        params: List[Any] = []

        if norm_country:
            where.append("country ILIKE %s")
            params.append(f"%{norm_country}%")
        elif region:
            where.append("(country ILIKE %s OR region ILIKE %s)")
            params.extend([f"%{region}%", f"%{region}%"]) 

        if norm_city:
            where.append("city ILIKE %s")
            params.append(f"%{norm_city}%")

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        q = f"""
          SELECT uuid, title, summary, gpt_summary, link, source, published,
                 region, country, city, category, threat_level, threat_label,
                 score, confidence, trend_direction,
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
                return rows or []
    except Exception as e:
        logger.warning("fetch_alerts_by_location_fuzzy failed: %s", e)
        return []

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
