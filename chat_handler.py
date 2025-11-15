# chat_handler.py — unmetered advisory orchestrator (client-facing helper) • v2025-08-13
# Revamped: safer DB timeouts, advisor call timeouts using futures (portable), robust datetime handling,
#           configurable env vars CHAT_DB_TIMEOUT, ADVISOR_TIMEOUT; improved logging and error paths.
# New: background async processing (202-style accept + polling) and per-step timing logs to aid debugging.

from __future__ import annotations
import json
import os
import time
import threading
import logging
import uuid
from datetime import datetime, timezone
from hashlib import sha1
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from dotenv import load_dotenv

# DB helpers
from db_utils import (
    fetch_alerts_from_db_strict_geo,
    fetch_past_incidents,
    fetch_user_profile,
    _conn,
)

# Geographic intelligence system
from location_service_consolidated import enhance_geographic_query

# Optional single-value fetch for verification fallback
try:
    from db_utils import fetch_one
except Exception:
    fetch_one = None  # best-effort fallback

# Advisor entrypoint (LLM)
from advisor import generate_advice

# Plan/usage are INFO-only here (no gating / no metering)
try:
    from plan_utils import get_plan, get_usage
except Exception:
    get_plan = None
    get_usage = None

from security_log_utils import log_security_event

# Optional city tools (safe fallbacks if missing)
try:
    from city_utils import fuzzy_match_city, normalize_city
except Exception:
    fuzzy_match_city = None
    normalize_city = None

# Optional verification util (preferred)
try:
    from verification_utils import verification_status as _verification_status
except Exception:
    _verification_status = None

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
if RAILWAY_ENV:
    log.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    log.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

load_dotenv()

# ---------------- Optional instrumentation & pooling imports ----------------
try:
    import prometheus_client
    from prometheus_client import Histogram, start_http_server
except Exception:
    prometheus_client = None
    Histogram = None
    start_http_server = None

try:
    import redis
except Exception:
    redis = None

try:
    from psycopg2.pool import ThreadedConnectionPool
except Exception:
    ThreadedConnectionPool = None

# ---------------- Metrics (histograms for percentiles) ----------------
METRICS_ENABLED = bool(os.getenv("CHAT_METRICS_ENABLED", "true").lower() in ("1", "true", "yes", "y"))
_METRICS_PORT = int(os.getenv("CHAT_METRICS_PORT", "8000"))
DB_FETCH_SECONDS = ADVISOR_SECONDS = OVERALL_SECONDS = None
if METRICS_ENABLED and Histogram is not None:
    try:
        DB_FETCH_SECONDS = Histogram(
            "chat_db_fetch_seconds",
            "DB fetch duration for chat alerts",
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        )
        ADVISOR_SECONDS = Histogram(
            "chat_advisor_seconds",
            "Advisor (LLM) call duration",
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 15.0, 30.0),
        )
        OVERALL_SECONDS = Histogram(
            "chat_overall_seconds",
            "Overall handle_user_query duration",
            buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0),
        )
        if start_http_server is not None:
            try:
                t = threading.Thread(target=lambda: start_http_server(_METRICS_PORT), daemon=True)
                t.start()
                log.info("Prometheus metrics server started on port %s", _METRICS_PORT)
            except Exception as e:
                log.warning("Failed to start Prometheus metrics server: %s", e)
    except Exception as e:
        log.warning("Failed to initialize metrics: %s", e)
        DB_FETCH_SECONDS = ADVISOR_SECONDS = OVERALL_SECONDS = None

# ---------------- Redis-backed (optional) rate limiter with in-process fallback ----------------
_redis_client = None
if redis is not None and os.getenv("CHAT_RATE_LIMIT_REDIS"):
    try:
        _redis_client = redis.from_url(os.getenv("CHAT_RATE_LIMIT_REDIS"))
        log.info("Redis rate limiter initialized")
    except Exception as e:
        log.warning("Redis rate limiter init failed, using in-memory: %s", e)
_inmem_rate = {}
_inmem_rate_lock = threading.Lock()

def check_rate_limit(user_email: str, per_min: int | None = None) -> bool:
    """
    Return True if allowed, False if rate limit exceeded.
    Uses Redis if CHAT_RATE_LIMIT_REDIS is set; otherwise uses a per-process in-memory sliding window.
    Default per_min is driven by CHAT_RATE_LIMIT_PER_MIN env (default 10).
    """
    try:
        limit = int(os.getenv("CHAT_RATE_LIMIT_PER_MIN", "10")) if per_min is None else int(per_min)
        window = 60
        key = f"rl:{user_email}:{window}:{limit}"
        if _redis_client:
            cur = _redis_client.incr(key)
            if cur == 1:
                _redis_client.expire(key, window)
            return cur <= limit
        else:
            now = time.time()
            with _inmem_rate_lock:
                arr = _inmem_rate.get(user_email, [])
                arr = [ts for ts in arr if ts > now - window]
                if len(arr) >= limit:
                    _inmem_rate[user_email] = arr
                    return False
                arr.append(now)
                _inmem_rate[user_email] = arr
            return True
    except Exception as e:
        # Fail open to avoid denying traffic on errors
        log.warning("Rate limiter error, failing open: %s", e)
        return True

# ---------------- Simple DB connection pool helpers ----------------
DB_POOL = None
if ThreadedConnectionPool and os.getenv("DATABASE_URL"):
    try:
        _minconn = int(os.getenv("DB_POOL_MIN", "1"))
        _maxconn = int(os.getenv("DB_POOL_MAX", "10"))
        DB_POOL = ThreadedConnectionPool(_minconn, _maxconn, os.getenv("DATABASE_URL"))
        log.info("Initialized DB pool min=%s max=%s", _minconn, _maxconn)
    except Exception as e:
        DB_POOL = None
        log.info("DB pool not initialized: %s", e)

def get_pooled_conn():
    """Return a pooled psycopg2 connection (or None). Caller should put_pooled_conn when done."""
    if DB_POOL:
        try:
            return DB_POOL.getconn()
        except Exception:
            return None
    return None

def put_pooled_conn(conn):
    """Return a connection to the pool."""
    if DB_POOL and conn is not None:
        try:
            DB_POOL.putconn(conn)
        except Exception:
            pass

# ---------------- In-memory cache & background jobs ----------------
CACHE_TTL = int(os.getenv("CHAT_CACHE_TTL", "1800"))  # seconds
RESPONSE_CACHE: Dict[str, Any] = {}
RESPONSE_CACHE_LOCK = threading.Lock()

# Background job store: job_id -> metadata
BACKGROUND_JOBS: Dict[str, Dict[str, Any]] = {}
BACKGROUND_JOBS_LOCK = threading.Lock()

def set_cache(key: str, value: Any) -> None:
    with RESPONSE_CACHE_LOCK:
        RESPONSE_CACHE[key] = (value, time.time())

def get_cache(key: str) -> Optional[Any]:
    with RESPONSE_CACHE_LOCK:
        entry = RESPONSE_CACHE.get(key)
        if not entry:
            return None
        value, ts = entry
        if time.time() - ts > CACHE_TTL:
            try:
                del RESPONSE_CACHE[key]
            except Exception:
                pass
            return None
        return value

# Add a simple memory limit to prevent cache bloat
def cleanup_cache() -> None:
    """Clean up cache if it gets too large"""
    with RESPONSE_CACHE_LOCK:
        if len(RESPONSE_CACHE) > 1000:
            # Remove oldest 20% of entries
            sorted_entries = sorted(RESPONSE_CACHE.items(), key=lambda x: x[1][1])
            to_remove = int(len(sorted_entries) * 0.2)
            for key, _ in sorted_entries[:to_remove]:
                del RESPONSE_CACHE[key]

# ---------------- Utils ----------------
def json_default(obj):
    if isinstance(obj, (datetime,)):
        # ISO with 'Z' for UTC
        if obj.tzinfo is None:
            return obj.replace(tzinfo=timezone.utc).isoformat()
        return obj.astimezone(timezone.utc).isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

def _ensure_str(val, default: str = "") -> str:
    return default if val is None else str(val)

def _ensure_num(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

def _ensure_label(val, default: str = "Unknown") -> str:
    if not val:
        return default
    s = str(val).strip()
    return s or default

def _ensure_list(val) -> List[Any]:
    if not val:
        return []
    if isinstance(val, list):
        return val
    return list(val) if isinstance(val, (set, tuple)) else [val]

def _iso_date(val) -> str:
    """
    Best-effort normalize date fields to ISO8601 (UTC). Returns '' if unknown.
    Accepts datetime, string, epoch int/float; tries common keys on alert dict.
    """
    if isinstance(val, dict):
        for k in ("published", "date", "timestamp", "pubDate", "published_at"):
            if k in val and val[k]:
                return _iso_date(val[k])
        return ""
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc).isoformat()
    if isinstance(val, (int, float)):
        try:
            dt = datetime.fromtimestamp(val, tz=timezone.utc)
            return dt.isoformat()
        except Exception:
            return ""
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return ""
        # Accept "Z" or offset
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            return s
    return ""

def _normalize_value(val: Optional[str], default: Optional[str] = None) -> Optional[str]:
    if not val or not isinstance(val, str):
        return default
    v = val.strip()
    if not v or v.lower() in ("all", "all regions", "all threats"):
        return default
    return v

def _normalize_region(region: Optional[str], city_list: Optional[List[str]] = None) -> Optional[str]:
    if not region:
        return None
    if fuzzy_match_city and city_list:
        try:
            match = fuzzy_match_city(region, city_list)
            return match if match else region
        except Exception:
            return region
    if normalize_city:
        try:
            return normalize_city(region)
        except Exception:
            return region
    return region

def _validate_region(region: Optional[str]) -> bool:
    """Reject broad/vague regions that will cause false matches"""
    if not region:
        return False
    vague_terms = {"middle east", "europe", "asia", "africa", "world", "global", 
                   "americas", "north america", "south america", "oceania", 
                   "scandinavia", "balkans", "central asia", "southeast asia"}
    return region.lower() not in vague_terms and len(region) > 3

def _session_id(email: str, body: Optional[Dict[str, Any]]) -> str:
    if body and body.get("session_id"):
        return str(body["session_id"])
    if email:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, email.strip().lower()))
    return str(uuid.uuid4())

def _is_verified(email: str) -> bool:
    """
    Preferred: verification_utils.verification_status
    Fallback: SELECT users.email_verified
    """
    try:
        if _verification_status:
            ok, _ = _verification_status(email)
            return bool(ok)
    except Exception:
        pass
    if fetch_one:
        try:
            row = fetch_one("SELECT email_verified FROM users WHERE email=%s", (email,))
            return bool(row and row[0])
        except Exception:
            return False
    return False

def _build_quota_obj(email: str, plan_name: str) -> Dict[str, Any]:
    """
    Helper to build quota object for frontend.
    Returns: {"used": int, "limit": int, "plan": str}
    """
    quota_obj = {
        "used": 0,
        "limit": 3,  # Default FREE limit
        "plan": plan_name
    }
    
    # Get current usage count
    if get_usage:
        try:
            current_usage = get_usage(email) or {}
            quota_obj["used"] = current_usage.get("chat_messages_used", 0)
        except Exception as e:
            log.warning("get_usage failed in _build_quota_obj: %s", e)
    
    # Determine limit based on plan (same logic as main.py)
    try:
        if plan_name == "PRO":
            quota_obj["limit"] = 1000
        elif plan_name in ("VIP", "ENTERPRISE"):
            quota_obj["limit"] = 5000
        else:
            # Try to get from plan_utils
            try:
                from plan_utils import get_plan_limits
                limits = get_plan_limits(email) or {}
                quota_obj["limit"] = limits.get("chat_messages_per_month", 3)
            except Exception:
                quota_obj["limit"] = 3
    except Exception as e:
        log.warning("Failed to determine limit in _build_quota_obj: %s", e)
    
    return quota_obj

# Small helper to produce a short, non-PII identifier for logs
def _short_id(s: Optional[str], length: int = 8) -> str:
    if not s:
        return "unknown"
    try:
        return sha1(s.encode()).hexdigest()[:length]
    except Exception:
        return "unknown"

# ---------------- Background Job Helpers ----------------
def _bg_cache_key(session_id: str) -> str:
    return f"bg:{session_id}"

def start_background_job(session_id: str, target_fn, *args, **kwargs) -> None:
    """
    Starts a daemon thread to run target_fn(*args, **kwargs).
    Stores job state in BACKGROUND_JOBS and stores result in cache under bg:<session_id>.
    """
    with BACKGROUND_JOBS_LOCK:
        if session_id in BACKGROUND_JOBS and BACKGROUND_JOBS[session_id].get("status") in ("running", "pending"):
            log.info("Background job for session %s already running", session_id)
            return
        BACKGROUND_JOBS[session_id] = {
            "status": "pending",
            "started_at": datetime.utcnow().isoformat() + "Z",
            "result": None,
            "error": None,
        }

    def _worker():
        log.info("Background worker started for session %s", session_id)
        with BACKGROUND_JOBS_LOCK:
            BACKGROUND_JOBS[session_id]["status"] = "running"
            BACKGROUND_JOBS[session_id]["started_at"] = datetime.utcnow().isoformat() + "Z"
        
        try:
            # Extract arguments - handle both old generic style and new specific style
            if target_fn == handle_user_query:
                # New async-first approach: direct call to handle_user_query
                message = args[0] if args else kwargs.get("message", "")
                email = args[1] if len(args) > 1 else kwargs.get("email", "")
                body = kwargs.get("body", {})
                
                # Call the full handle_user_query logic with proper parameters
                res = handle_user_query(message, email, body=body)
            else:
                # Legacy support: generic target function call
                res = target_fn(*args, **kwargs)
            
            # Store result in cache with metadata
            payload = res if isinstance(res, dict) else {"reply": str(res)}
            payload["_background"] = True
            payload["_completed_at"] = datetime.utcnow().isoformat() + "Z"
            
            set_cache(_bg_cache_key(session_id), payload)
            
            with BACKGROUND_JOBS_LOCK:
                BACKGROUND_JOBS[session_id]["status"] = "done"
                BACKGROUND_JOBS[session_id]["result"] = payload
                
        except Exception as e:
            log.exception("Background worker for session %s failed: %s", session_id, e)
            with BACKGROUND_JOBS_LOCK:
                BACKGROUND_JOBS[session_id]["status"] = "failed"
                BACKGROUND_JOBS[session_id]["error"] = str(e)
            
            # Store error result in cache so clients can retrieve it
            error_payload = {
                "error": str(e),
                "reply": "Background processing failed. Please try again.",
                "_background": True,
                "_error": True,
                "_completed_at": datetime.utcnow().isoformat() + "Z"
            }
            set_cache(_bg_cache_key(session_id), error_payload)
            
            # Log security event for monitoring
            try:
                log_security_event(event_type="background_job_failed", details=f"session={session_id} error={e}")
            except Exception:
                pass
    t = threading.Thread(target=_worker, daemon=True)
    t.start()

def get_background_status(session_id: str) -> Dict[str, Any]:
    """
    Returns job metadata and result if available.
    """
    with BACKGROUND_JOBS_LOCK:
        meta = BACKGROUND_JOBS.get(session_id, {}).copy()
    result = get_cache(_bg_cache_key(session_id))
    return {"job": meta or {"status": "unknown"}, "result": result}

# ---------------- Core ----------------
def handle_user_query(
    message: str | Dict[str, Any],
    email: str,
    region: Optional[str] = None,
    threat_type: Optional[str] = None,   # maps to alerts.category
    city_list: Optional[List[str]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Entry: assemble context, fetch alerts, call advisor, and return a structured response.
    This version uses timeouts for DB and advisor steps to avoid blocking HTTP gateways.
    Also supports background processing fallback: if ADVISOR_TIMEOUT triggers and ASYNC_FALLBACK is true,
    it will accept the request and process the advisory in background; results are available via get_background_status(session_id).
    """
    overall_start = time.perf_counter()
    log.info("handle_user_query: ENTERED | user=%s", _short_id(email))

    if not email:
        log_security_event(event_type="missing_email", details="handle_user_query called without email")
        raise ValueError("handle_user_query requires a valid authenticated user email.")

    # ---- Initialize timing variables with defaults ----
    setup_start = time.perf_counter()
    setup_elapsed = 0.0
    db_elapsed = 0.0 
    preprocessing_elapsed = 0.0
    advisor_elapsed = 0.0
    
    # ---- Soft verification guard (defense-in-depth) ----
    if not _is_verified(email):
        log_security_event(
            event_type="chat_denied_unverified",
            email=email,
            details="Soft guard in chat_handler blocked unverified user",
        )
        return {
            "error": "Email not verified. Please verify your email to use chat.",
            "verify_required": True,
            "actions": {"send_code": "/auth/verify/send", "confirm_code": "/auth/verify/confirm"},
        }

    # Extract parameters from message dict (compatible with main.py _advisor_call)
    if isinstance(message, dict):
        # Extract from the structure used by main.py's _advisor_call
        query = message.get("query", "")
        profile_data = message.get("profile_data", {})
        input_data = message.get("input_data", {})
        
        # Extract region and threat_type from input_data if provided
        if not region and "region" in input_data:
            region = input_data.get("region")
        if not threat_type and "threat_type" in input_data:
            threat_type = input_data.get("threat_type")
        
        # Extract city_list from input_data if provided
        if not city_list and "city_list" in input_data:
            city_list = input_data.get("city_list")
        
        # Use body if provided in input_data
        if not body and "body" in input_data:
            body = input_data.get("body", {})
    else:
        # Legacy string-only support
        query = str(message or "")
        profile_data = {}
        input_data = {}

    query = (query or "").strip()
    if not query:
        query = "Please provide a security threat assessment for my area."

    log.info("Query content (truncated): %s", (query[:200] + "...") if len(query) > 200 else query)

    # Plan/usage are informational only
    plan_name = "FREE"
    if get_plan:
        try:
            p = get_plan(email)
            plan_name = (p or "FREE").upper()
        except Exception as e:
            log.warning("get_plan failed: %s", e)

    usage_info: Dict[str, Any] = {"email_short": _short_id(email)}
    if get_usage:
        try:
            usage_info.update(get_usage(email) or {})
        except Exception as e:
            log.warning("get_usage failed: %s", e)

    # Extract location intent from the natural-language query if no explicit region provided
    extracted_city = None
    extracted_country = None
    try:
        if not region:
            from location_extractor import extract_location_from_query
            loc = extract_location_from_query(query)
            extracted_city = (loc or {}).get("city")
            extracted_country = (loc or {}).get("country")
            # Seed region with the most specific stable token to reuse existing geo logic
            if extracted_city:
                region = extracted_city
            elif extracted_country:
                region = extracted_country
            log.info("Location extracted from query: city=%s country=%s method=%s", extracted_city, extracted_country, (loc or {}).get("method"))
    except Exception as e:
        log.warning("Location extraction failed: %s", e)

    # Normalize region/category
    region = _normalize_value(region, None)
    threat_type = _normalize_value(threat_type, None)
    if region and city_list:
        region = _normalize_region(region, city_list)
    log.debug("Filters | region=%r category(threat_type)=%r", region, threat_type)

    # Add strict region validation BEFORE calling DB
    if region and not _validate_region(region):
        log.warning("Vague region '%s' rejected - asking for clarification", region)
        return {
            "reply": f"Please specify a city or country within '{region}' for precise alerts.",
            "alerts": [],
            "no_data": True,
            "metadata": {"vague_region": True},
            "session_id": _session_id(email, body),
            "usage": usage_info
        }

    # Session
    session_id = _session_id(email, body)

    # Cache key (after filters)
    cache_key = sha1(json.dumps(
        {"query": query, "region": region, "category": threat_type, "session_id": session_id},
        sort_keys=True, default=json_default
    ).encode("utf-8")).hexdigest()
    cached = get_cache(cache_key)
    if cached is not None:
        log.info("handle_user_query: cache HIT | user=%s session=%s", _short_id(email), session_id[:8] if session_id else "unk")
        log_security_event(event_type="cache_hit", email=email, plan=plan_name, details=f"cache_key={cache_key}")
        # Update quota in cached response
        if isinstance(cached, dict):
            cached["quota"] = _build_quota_obj(email, plan_name)
        return cached

    # ---------------- Fetch alerts (with timeout) ----------------
    db_alerts: List[Dict[str, Any]] = []
    db_start = time.perf_counter()
    
    # ---- Timing checkpoint: Setup phase complete ----
    setup_elapsed = db_start - setup_start
    log.info("Setup phase: %.3fs | user=%s", setup_elapsed, _short_id(email))
    
    try:
        log.info("DB: fetch_alerts_from_db_strict_geo(...) | user=%s session=%s", _short_id(email), session_id[:8] if session_id else "unk")
        
        # Enhanced geographic parameter handling using dynamic intelligence
        try:
            # Log input parameters for debugging (sanitized)
            log.info("Geographic resolution starting", extra={"user": _short_id(email), "original_region": region, "threat_type": threat_type})
            
            # Apply geographic intelligence enhancement
            geo_params = enhance_geographic_query(region)
            country_param = geo_params.get("country")
            city_param = geo_params.get("city")

            # If we extracted explicit location from the query, prefer it
            if extracted_country and not country_param:
                country_param = extracted_country
            if extracted_city and not city_param:
                city_param = extracted_city
            region_param = geo_params.get("region")
            
            # Defensive validation of resolved parameters
            if region_param and not isinstance(region_param, str):
                log.warning("Invalid region_param type, falling back to original | user=%s", _short_id(email))
                region_param = region
            if country_param and not isinstance(country_param, str):
                log.warning("Invalid country_param type, clearing | user=%s", _short_id(email))
                country_param = None
            if city_param and not isinstance(city_param, str):
                log.warning("Invalid city_param type, clearing | user=%s", _short_id(email))
                city_param = None
            
            # Enhanced logging with more detail (also include short user id)
            log.info(
                f"Geographic intelligence resolved: input='{region}' resolved_region='{region_param}' detected_country='{country_param}' detected_city='{city_param}' method={geo_params.get('location_method','unknown')} confidence={geo_params.get('location_confidence','unknown')} user={_short_id(email)}"
            )
            
            # Backwards-compatible simple log line for ops dashboards
            log.info(f"QUERY GEO SUCCESS: region='{region_param}' country='{country_param}' city='{city_param}' user={_short_id(email)}")
            
        except Exception as e:
            log.warning("Geographic intelligence failed, applying defensive fallback: %s", e)
            log.warning("Exception details: type=%s args=%s", type(e).__name__, getattr(e, "args", "N/A"))
            
            # Defensive fallback with safe defaults
            country_param = None
            city_param = None
            region_param = region if region and isinstance(region, str) else None
            
            # Log fallback state clearly
            log.info(f"QUERY GEO FALLBACK: region='{region_param}' country='{country_param}' city='{city_param}' user={_short_id(email)} error='{str(e)[:100]}'")
            
            # Security event for geographic intelligence failures (include full email)
            try:
                log_security_event(
                    event_type="geographic_intelligence_failed", 
                    email=email, 
                    plan=plan_name, 
                    details=f"region='{region}' error={str(e)[:200]}"
                )
            except Exception:
                pass  # Don't let logging failures cascade

        # Run DB fetch in a worker with a hard timeout to avoid blocking the request forever
        if fetch_alerts_from_db_strict_geo:
            db_timeout = int(os.getenv("CHAT_DB_TIMEOUT", "30"))  # seconds
            try:
                # Enhanced parameter logging with validation before DB call
                log.info(
                    f"Preparing database query | user={_short_id(email)} session={session_id[:8] if session_id else 'unk'} region_param={region_param} country_param={country_param} city_param={city_param} threat_type={threat_type} alerts_limit={int(os.getenv('CHAT_ALERTS_LIMIT','20'))} db_timeout={db_timeout}"
                )
                
                # Validate parameters before query
                params_valid = True
                if region_param is not None and not isinstance(region_param, str):
                    log.warning("Invalid region_param for DB query: %s", type(region_param))
                    params_valid = False
                if country_param is not None and not isinstance(country_param, str):
                    log.warning("Invalid country_param for DB query: %s", type(country_param))
                    params_valid = False
                if city_param is not None and not isinstance(city_param, str):
                    log.warning("Invalid city_param for DB query: %s", type(city_param))
                    params_valid = False
                    
                if not params_valid:
                    log.error("DB query aborted due to invalid parameters | user=%s", _short_id(email))
                    db_alerts = []
                else:
                    log.info(f"EXECUTING DB QUERY: region='{region_param}' country='{country_param}' city='{city_param}' threat='{threat_type}' timeout={db_timeout}s user={_short_id(email)}")
                    with ThreadPoolExecutor(max_workers=1) as ex:
                        future = ex.submit(
                            fetch_alerts_from_db_strict_geo,
                            region_param,
                            country_param,
                            city_param,
                            threat_type,
                            int(os.getenv("CHAT_ALERTS_LIMIT", "20")),
                        )
                        db_alerts = future.result(timeout=db_timeout) or []
                # Defensive validation and logging of query results
                try:
                    if db_alerts is None:
                        log.warning("DB query returned None, converting to empty list | user=%s", _short_id(email))
                        db_alerts = []
                    elif not isinstance(db_alerts, list):
                        log.warning("DB query returned non-list type %s, converting | user=%s", type(db_alerts), _short_id(email))
                        # If it's iterable, make a list; otherwise drop to empty list
                        try:
                            db_alerts = list(db_alerts) if hasattr(db_alerts, '__iter__') else []
                        except Exception:
                            db_alerts = []
                    
                    results_count = len(db_alerts)
                    log.info(
                        f"Database query completed successfully | results_count={results_count} query_region={region_param} query_country={country_param} query_city={city_param} query_threat={threat_type} db_timeout_used={db_timeout} user={_short_id(email)} session={session_id[:8] if session_id else 'unk'}"
                    )
                    log.info(f"DB QUERY SUCCESS: {results_count} alerts returned for region='{region_param}' country='{country_param}' city='{city_param}' user={_short_id(email)}")
                    
                except Exception as result_error:
                    log.error("Error processing DB query results: %s | user=%s", result_error, _short_id(email))
                    results_count = -1
                    db_alerts = []
            except FuturesTimeout:
                log.error(
                    "Database fetch timed out - this may indicate DB performance issues or network problems | timeout_seconds=%s user=%s region=%s country=%s city=%s",
                    db_timeout, _short_id(email), region_param, country_param, city_param
                )
                log.error(f"DB TIMEOUT: Query timed out after {db_timeout}s for region='{region_param}' country='{country_param}' city='{city_param}' user={_short_id(email)}")
                try:
                    log_security_event(
                        event_type="db_alerts_fetch_timeout", 
                        email=email, 
                        plan=plan_name, 
                        details=f"timeout={db_timeout}s region='{region_param}' country='{country_param}' city='{city_param}'"
                    )
                except Exception:
                    pass
                db_alerts = []
            except Exception as e:
                log.error(
                    "Database fetch failed with unexpected error: %s | user=%s",
                    type(e).__name__, _short_id(email)
                )
                log.error(f"DB ERROR: {type(e).__name__}: {e} for region='{region_param}' country='{country_param}' city='{city_param}' user={_short_id(email)}")
                try:
                    log_security_event(
                        event_type="db_alerts_fetch_failed", 
                        email=email, 
                        plan=plan_name, 
                        details=f"error={type(e).__name__}: {str(e)[:200]} region='{region_param}'"
                    )
                except Exception:
                    pass
                db_alerts = []
        else:
            db_alerts = []

        count = len(db_alerts or [])
        db_elapsed = time.perf_counter() - db_start
        log.info("DB phase: %.3fs (%d alerts) | user=%s", db_elapsed, count, _short_id(email))
        
        # Track slow DB queries
        if db_elapsed > 20:  # Warn on slow DB queries (>20s)
            try:
                log_security_event(
                    event_type="slow_db_query", 
                    email=email, 
                    plan=plan_name, 
                    details=f"DB query took {db_elapsed:.2f}s for {count} alerts"
                )
            except Exception:
                pass
                
        try:
            log_security_event(event_type="db_alerts_fetched", email=email, plan=plan_name, details=f"{count} alerts")
        except Exception:
            pass
    except Exception as e:
        db_elapsed = time.perf_counter() - db_start
        log.error("DB fetch failed unexpectedly after %.3fs: %s", db_elapsed, e)
        usage_info["fallback_reason"] = "alert_fetch_error"
        try:
            log_security_event(event_type="db_alerts_fetch_failed", email=email, plan=plan_name, details=str(e))
        except Exception:
            pass
        
        # Build quota object for error response
        quota_obj = _build_quota_obj(email, plan_name)
        
        return {
            "reply": f"System error fetching alerts: {e}",
            "plan": plan_name,
            "quota": quota_obj,
            "alerts": [],
            "usage": usage_info,
            "session_id": session_id,
        }

    # ---------------- Historical context ----------------
    historical_alerts: List[Dict[str, Any]] = []
    history_category = None
    if db_alerts:
        cats = {a.get("category") for a in db_alerts if a.get("category")}
        history_category = next(iter(cats)) if cats else None
    try:
        historical_alerts = fetch_past_incidents(
            region=region, category=history_category, days=int(os.getenv("CHAT_HISTORY_DAYS", "90")), limit=100
        )
        log.info("[HIST] %d historical for region=%s category=%s | user=%s", len(historical_alerts), region, history_category, _short_id(email))
    except Exception as e:
        log.warning("[HIST] fetch_past_incidents failed: %s", e)

    # ---------------- User profile ----------------
    user_profile: Dict[str, Any] = {}
    try:
        user_profile = fetch_user_profile(email) or {}
        # Merge with profile_data from main.py if provided
        if profile_data and isinstance(profile_data, dict):
            user_profile.update(profile_data)
        log.info("[PROFILE] Loaded profile for %s", _short_id(email))
    except Exception as e:
        log.warning("[PROFILE] fetch_user_profile failed: %s", e)

    # ---------------- Proactive trigger heuristic ----------------
    all_low = False
    alerts_stale = False
    
    if db_alerts:
        try:
            # Convert all scores to float before comparison
            scores = []
            for alert in db_alerts:
                score_str = alert.get("score")
                if score_str is not None:
                    try:
                        scores.append(float(score_str))
                    except (TypeError, ValueError):
                        scores.append(0.0)
                else:
                    scores.append(0.0)
            
            all_low = all(score < 55 for score in scores) if scores else False
        except Exception as e:
            log.warning("Error calculating all_low heuristic: %s", e)
            all_low = False

        # Check if alerts are stale - use robust datetime parsing
        try:
            valid_dates: List[datetime] = []
            for a in db_alerts:
                iso = _iso_date(a)
                if not iso:
                    continue
                try:
                    if iso.endswith("Z"):
                        iso = iso[:-1] + "+00:00"
                    dt = datetime.fromisoformat(iso)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    valid_dates.append(dt.astimezone(timezone.utc))
                except Exception:
                    continue
            if valid_dates:
                latest_dt = max(valid_dates)
                current_time = datetime.now(timezone.utc)
                alerts_stale = (current_time - latest_dt).days >= 7
            else:
                alerts_stale = False
        except Exception as e:
            log.warning("Error calculating alerts_stale heuristic: %s", e)
            alerts_stale = False

    # ----------- FUZZY FALLBACK BEFORE NO-DATA GUARD -----------
    if not db_alerts:
        try:
            from db_utils import fetch_alerts_by_location_fuzzy
        except Exception:
            fetch_alerts_by_location_fuzzy = None  # type: ignore

        if fetch_alerts_by_location_fuzzy and (extracted_city or extracted_country or region):
            try:
                log.info("Attempting fuzzy location fallback: city=%s country=%s region=%s", extracted_city, extracted_country, region)
                db_alerts = fetch_alerts_by_location_fuzzy(
                    city=extracted_city,
                    country=extracted_country,
                    region=region,
                    limit=int(os.getenv("CHAT_ALERTS_LIMIT", "20")),
                ) or []
                if db_alerts:
                    log.info("Fuzzy fallback succeeded with %d alert(s)", len(db_alerts))
            except Exception as e:
                log.warning("Fuzzy fallback failed: %s", e)

    # ----------- STRICT NO-DATA GUARD (no LLM on empty geo result) -----------
    if not db_alerts:
        log.info("No alerts found for query='%s', region='%s', threat_type='%s' | user=%s", query, region, threat_type, _short_id(email))
        requested_loc = {
            "city": extracted_city,
            "country": extracted_country,
            "region": region,
        }
        reply_text = (
            "### No Intelligence Available\n\n"
            f"Query: {query}\n\n"
            f"Requested Location: {requested_loc.get('city') or requested_loc.get('country') or requested_loc.get('region') or 'Unknown'}\n\n"
            "We don't have recent alerts for this location.\n\n"
            "What you can do:\n"
            "1. Try a nearby major city (e.g., 'Belgrade' instead of suburb)\n"
            "2. Broaden to country-level (e.g., 'Serbia')\n"
            "3. Set monitoring and we’ll notify on new incidents\n"
        )
        payload = {
            "reply": reply_text,
            "plan": plan_name,
            "quota": _build_quota_obj(email, plan_name),
            "alerts": [],
            "usage": usage_info,
            "session_id": session_id,
            "no_data": True,
            "metadata": {"requested_location": requested_loc},
        }
        set_cache(cache_key, payload)
        try:
            log_security_event(event_type="no_data_response", email=email, plan=plan_name, details=f"query={query[:120]}")
        except Exception:
            pass
        return payload

    # ---------------- Advisor call (with timeout via futures) ----------------
    advisory_result: Dict[str, Any] = {}
    ADVISOR_TIMEOUT = int(os.getenv("ADVISOR_TIMEOUT", "45"))
    ASYNC_FALLBACK = os.getenv("ASYNC_FALLBACK", "true").lower() in ("1", "true", "yes", "y")
    advisor_kwargs = {
        "email": email,
        "region": region,
        "threat_type": threat_type,
        "user_profile": user_profile,
        "historical_alerts": historical_alerts,
    }

    advisor_start = time.perf_counter()
    
    # ---- Timing checkpoint: Historical/geographic processing complete ----
    preprocessing_elapsed = advisor_start - db_start
    log.info("Preprocessing phase: %.3fs | user=%s", preprocessing_elapsed, _short_id(email))
    
    # ----------- LOW CONFIDENCE HARD-STOP (avoid false confidence) -----------
    try:
        best_conf = 0.0
        for a in db_alerts:
            try:
                c = float(a.get("confidence") or 0)
            except (ValueError, TypeError):
                c = 0.0
            if c > best_conf:
                best_conf = c
        MIN_CONF = float(os.getenv("CHAT_MIN_CONFIDENCE", "0.40"))
        if best_conf < MIN_CONF:
            warn = (
                "### Low Confidence — Advisory Withheld\n\n"
                f"Top alert confidence: {int(best_conf*100)}% (min required {int(MIN_CONF*100)}%)\n\n"
                "We don't have sufficient quality signals for a reliable advisory.\n\n"
                "Try broadening the location (city → country) or query timeframe."
            )
            payload = {
                "reply": warn,
                "plan": plan_name,
                "quota": _build_quota_obj(email, plan_name),
                "alerts": [],
                "usage": usage_info,
                "session_id": session_id,
                "low_confidence": True,
            }
            set_cache(cache_key, payload)
            try:
                log_security_event(event_type="low_confidence_block", email=email, plan=plan_name, details=f"best_conf={best_conf:.2f}")
            except Exception:
                pass
            return payload
    except Exception as e:
        log.warning("Low-confidence guard failed open: %s", e)

    try:
        advisor_extra = dict(advisor_kwargs)
        user_prof = advisor_extra.pop("user_profile", None)

        with ThreadPoolExecutor(max_workers=1) as ex:
            if db_alerts and (all_low or alerts_stale):
                log.info("[Proactive Mode] All alerts low or stale → proactive advisory | user=%s", _short_id(email))
                future = ex.submit(generate_advice, query, db_alerts, user_prof, **advisor_extra)
                try:
                    advisory_result = future.result(timeout=ADVISOR_TIMEOUT) or {}
                    advisory_result["proactive_triggered"] = True
                    usage_info["proactive_triggered"] = True
                except FuturesTimeout:
                    adv_elapsed = time.perf_counter() - advisor_start
                    log.error("Advisor timed out after %ss (proactive mode) [%.3fs elapsed]", ADVISOR_TIMEOUT, adv_elapsed)
                    usage_info["fallback_reason"] = "advisor_timeout"
                    try:
                        log_security_event(event_type="advice_generation_timeout", email=email, plan=plan_name, details=f"{ADVISOR_TIMEOUT}s timeout")
                    except Exception:
                        pass
                    if ASYNC_FALLBACK:
                        bg_session = session_id
                        start_background_job(bg_session, generate_advice, query, db_alerts, user_prof, **advisor_extra)
                        reply_text = "Accepted for background processing (proactive). Poll for results with session_id."
                        payload = {
                            "accepted": True,
                            "session_id": bg_session,
                            "message": reply_text,
                            "plan": plan_name,
                            "quota": _build_quota_obj(email, plan_name),
                        }
                        set_cache(cache_key, payload)
                        try:
                            log_security_event(event_type="response_accepted_bg", email=email, plan=plan_name, details=f"bg_session={bg_session}")
                        except Exception:
                            pass
                        return payload
                    else:
                        advisory_result = {"reply": "Request timed out. Please try a shorter or simpler query.", "timeout": True}
            else:
                future = ex.submit(generate_advice, query, db_alerts, user_prof, **advisor_extra)
                try:
                    advisory_result = future.result(timeout=ADVISOR_TIMEOUT) or {}
                    advisory_result["proactive_triggered"] = False
                except FuturesTimeout:
                    adv_elapsed = time.perf_counter() - advisor_start
                    log.error("Advisor timed out after %ss [%.3fs elapsed]", ADVISOR_TIMEOUT, adv_elapsed)
                    usage_info["fallback_reason"] = "advisor_timeout"
                    try:
                        log_security_event(event_type="advice_generation_timeout", email=email, plan=plan_name, details=f"{ADVISOR_TIMEOUT}s timeout")
                    except Exception:
                        pass
                    if ASYNC_FALLBACK:
                        bg_session = session_id
                        start_background_job(bg_session, generate_advice, query, db_alerts, user_prof, **advisor_extra)
                        reply_text = "Accepted for background processing. Poll for results with session_id."
                        payload = {
                            "accepted": True,
                            "session_id": bg_session,
                            "message": reply_text,
                            "plan": plan_name,
                            "quota": _build_quota_obj(email, plan_name),
                        }
                        set_cache(cache_key, payload)
                        try:
                            log_security_event(event_type="response_accepted_bg", email=email, plan=plan_name, details=f"bg_session={bg_session}")
                        except Exception:
                            pass
                        return payload
                    else:
                        advisory_result = {"reply": "Request timed out. Please try a shorter or simpler query.", "timeout": True}
    except Exception as e:
        adv_elapsed = time.perf_counter() - advisor_start
        log.error("Advisor failed after %.3fs: %s", adv_elapsed, e)
        advisory_result = {"reply": f"System error generating advice: {e}"}
        usage_info["fallback_reason"] = "advisor_error"
        try:
            log_security_event(event_type="advice_generation_failed", email=email, plan=plan_name, details=str(e))
        except Exception:
            pass

    advisor_elapsed = time.perf_counter() - advisor_start
    log.info("Advisor phase: %.3fs | user=%s", advisor_elapsed, _short_id(email))
    
    # Track slow advisor calls
    if advisor_elapsed > 60:  # Warn on slow advisor calls (>60s)
        try:
            log_security_event(
                event_type="slow_advisor_call", 
                email=email, 
                plan=plan_name, 
                details=f"Advisor took {advisor_elapsed:.2f}s"
            )
        except Exception:
            pass

    # ---------------- Build alert payloads ----------------
    results: List[Dict[str, Any]] = []
    for alert in db_alerts or []:
        # Ensure ALL numerical fields are properly converted to floats
        raw_score = alert.get("score")
        try:
            score_float = float(raw_score) if raw_score is not None else 0.0
        except (TypeError, ValueError):
            score_float = 0.0
            
        raw_confidence = alert.get("confidence")
        try:
            confidence_float = float(raw_confidence) if raw_confidence is not None else 0.0
        except (TypeError, ValueError):
            confidence_float = 0.0

        raw_trend_score = alert.get("trend_score")
        try:
            trend_score_float = float(raw_trend_score) if raw_trend_score is not None else 0.0
        except (TypeError, ValueError):
            trend_score_float = 0.0

        raw_future_risk = alert.get("future_risk_probability")
        try:
            future_risk_float = float(raw_future_risk) if raw_future_risk is not None else 0.0
        except (TypeError, ValueError):
            future_risk_float = 0.0
            
        results.append({
            "uuid": _ensure_str(alert.get("uuid", "")),
            "title": _ensure_str(alert.get("title", "")),
            "summary": _ensure_str(alert.get("gpt_summary") or alert.get("summary", "")),
            "link": _ensure_str(alert.get("link", "")),
            "source": _ensure_str(alert.get("source", "")),
            "category": _ensure_str(alert.get("category") or alert.get("type") or ""),
            "subcategory": _ensure_str(alert.get("subcategory", "")),
            "threat_level": _ensure_label(alert.get("threat_level", "")),
            "threat_label": _ensure_label(alert.get("threat_label") or alert.get("label") or ""),
            "score": score_float,
            "confidence": confidence_float,
            "published": _iso_date(alert),
            "city": _ensure_str(alert.get("city", "")),
            "country": _ensure_str(alert.get("country", "")),
            "region": _ensure_str(alert.get("region", "")),
            "reasoning": _ensure_str(alert.get("reasoning", "")),
            "forecast": _ensure_str(alert.get("forecast", "")),
            "historical_context": _ensure_str(alert.get("historical_context", "")),
            "sentiment": _ensure_str(alert.get("sentiment", "")),
            "legal_risk": _ensure_str(alert.get("legal_risk", "")),
            "cyber_ot_risk": _ensure_str(alert.get("cyber_ot_risk", "")),
            "environmental_epidemic_risk": _ensure_str(alert.get("environmental_epidemic_risk", "")),
            "domains": _ensure_list(alert.get("domains")),
            "trend_direction": _ensure_str(alert.get("trend_direction", "")),
            "trend_score": trend_score_float,
            "trend_score_msg": _ensure_str(alert.get("trend_score_msg", "")),
            "future_risk_probability": future_risk_float,
            "anomaly_flag": bool(alert.get("anomaly_flag") or alert.get("is_anomaly") or False),
            "early_warning_indicators": _ensure_list(alert.get("early_warning_indicators")),
            "reports_analyzed": int(alert.get("reports_analyzed") or 0),
            "sources": _ensure_list(alert.get("sources")),
        })

    log.info("Alerts processed: %d | user=%s", len(results), _short_id(email))
    try:
        log_security_event(event_type="alerts_processed", email=email, plan=plan_name, details=f"count={len(results)}")
    except Exception:
        pass

    # Optional telemetry
    try:
        label_counts: Dict[str, int] = {}
        for a in results:
            lab = a.get("threat_label") or a.get("threat_level") or "Unknown"
            label_counts[lab] = label_counts.get(lab, 0) + 1
        log.info("[METRICS] label_counts=%s | user=%s", label_counts, _short_id(email))
        try:
            log_security_event(event_type="alerts_label_count", email=email, plan=plan_name, details=str(label_counts))
        except Exception:
            pass
    except Exception:
        pass

    # ---------------- Return & cache ----------------
    reply_text = advisory_result.get("reply", "No response generated.") if isinstance(advisory_result, dict) else str(advisory_result)
    
    quota_obj = _build_quota_obj(email, plan_name)
    
    payload = {
        "reply": reply_text,
        "plan": plan_name,
        "quota": quota_obj,
        "alerts": results,
        "usage": usage_info,
        "session_id": session_id,
        "metadata": advisory_result if isinstance(advisory_result, dict) else {}
    }
    set_cache(cache_key, payload)
    overall_elapsed = time.perf_counter() - overall_start
    
    # ---- Enhanced timing summary with phase breakdown ----
    log.info("=== TIMING SUMMARY ===")
    log.info("Setup phase: %.3fs", setup_elapsed)
    log.info("DB phase: %.3fs", db_elapsed)
    log.info("Preprocessing phase: %.3fs", preprocessing_elapsed) 
    log.info("Advisor phase: %.3fs", advisor_elapsed)
    log.info("Total request time: %.3fs | user=%s", overall_elapsed, _short_id(email))
    log.info("=== END TIMING ===")
    
    # Track slow requests and log security event
    if overall_elapsed > 50:  # Warn on slow requests (>50s)
        try:
            log_security_event(
                event_type="slow_request",
                email=email, 
                plan=plan_name,
                details=f"Total: {overall_elapsed:.2f}s (Setup: {setup_elapsed:.2f}s, DB: {db_elapsed:.2f}s, Preprocessing: {preprocessing_elapsed:.2f}s, Advisor: {advisor_elapsed:.2f}s)"
            )
        except Exception:
            pass
    
    try:
        log_security_event(event_type="response_sent", email=email, plan=plan_name, details=f"query={query[:120]} elapsed={overall_elapsed:.3f}s")
    except Exception:
        pass
    return payload

# ---------------- Background job monitoring helpers ----------------
def list_background_jobs() -> Dict[str, Dict[str, Any]]:
    """Return a shallow copy of background jobs for monitoring (session_id -> metadata)."""
    with BACKGROUND_JOBS_LOCK:
        return {k: v.copy() for k, v in BACKGROUND_JOBS.items()}

def cancel_background_job(session_id: str) -> bool:
    """Best-effort mark a background job for cancellation. Worker must respect cancel_requested flag."""
    with BACKGROUND_JOBS_LOCK:
        job = BACKGROUND_JOBS.get(session_id)
        if not job:
            return False
        job["cancel_requested"] = True
    return True

# ---------------- Geographic coordinate parsing / bounds checking ----------------
def _parse_coords(s: Optional[str]) -> Optional[Dict[str, float]]:
    """
    Parse 'lat,lon' or 'lat lon' into {'lat': float, 'lon': float}.
    Returns None if parse fails or values out-of-bounds.
    """
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    sep = "," if "," in s else " "
    parts = [p.strip() for p in s.split(sep) if p.strip()]
    if len(parts) != 2:
        return None
    try:
        lat = float(parts[0]); lon = float(parts[1])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return {"lat": lat, "lon": lon}
    except Exception:
        return None