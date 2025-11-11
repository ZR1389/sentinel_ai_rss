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
            res = target_fn(*args, **kwargs)
            # Normalize result (expected to be dict)
            out = res if isinstance(res, dict) else {"reply": str(res)}
            # Persist into cache for quick retrieval; include sentinel metadata
            payload = out
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
            log_security_event(event_type="background_job_failed", details=f"session={session_id} error={e}")
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
    log.info("handle_user_query: ENTERED | email=%s", email)

    if not email:
        log_security_event(event_type="missing_email", details="handle_user_query called without email")
        raise ValueError("handle_user_query requires a valid authenticated user email.")

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

    log.info("Query content: %s", query)

    # Plan/usage are informational only
    plan_name = "FREE"
    if get_plan:
        try:
            p = get_plan(email)
            plan_name = (p or "FREE").upper()
        except Exception as e:
            log.warning("get_plan failed: %s", e)

    usage_info: Dict[str, Any] = {"email": email}
    if get_usage:
        try:
            usage_info.update(get_usage(email) or {})
        except Exception as e:
            log.warning("get_usage failed: %s", e)

    # Normalize region/category
    region = _normalize_value(region, None)
    threat_type = _normalize_value(threat_type, None)
    if region and city_list:
        region = _normalize_region(region, city_list)
    log.debug("Filters | region=%r category(threat_type)=%r", region, threat_type)

    # Session
    session_id = _session_id(email, body)

    # Cache key (after filters)
    cache_key = sha1(json.dumps(
        {"query": query, "region": region, "category": threat_type, "session_id": session_id},
        sort_keys=True, default=json_default
    ).encode("utf-8")).hexdigest()
    cached = get_cache(cache_key)
    if cached is not None:
        log.info("handle_user_query: cache HIT")
        log_security_event(event_type="cache_hit", email=email, plan=plan_name, details=f"cache_key={cache_key}")
        # Update quota in cached response
        if isinstance(cached, dict):
            cached["quota"] = _build_quota_obj(email, plan_name)
        return cached

    # ---------------- Fetch alerts (with timeout) ----------------
    db_alerts: List[Dict[str, Any]] = []
    db_start = time.perf_counter()
    try:
        log.info("DB: fetch_alerts_from_db_strict_geo(...)")
        
        # Enhanced geographic parameter handling using dynamic intelligence
        try:
            geo_params = enhance_geographic_query(region)
            country_param = geo_params.get('country')
            city_param = geo_params.get('city')
            region_param = geo_params.get('region')
            
            if country_param:
                log.info(f"Geographic intelligence: '{region}' → country='{country_param}', city='{city_param}'")
        except Exception as e:
            log.warning(f"Geographic intelligence failed, using original region: {e}")
            country_param = None
            city_param = None
            region_param = region

        # Run DB fetch in a worker with a hard timeout to avoid blocking the request forever
        if fetch_alerts_from_db_strict_geo:
            db_timeout = int(os.getenv("CHAT_DB_TIMEOUT", "30"))  # seconds
            try:
                with ThreadPoolExecutor(max_workers=1) as ex:
                    future = ex.submit(
                        fetch_alerts_from_db_strict_geo,
                        region_param,
                        country_param,
                        city_param,
                        threat_type,
                        int(os.getenv("CHAT_ALERTSLimit", os.getenv("CHAT_ALERTS_LIMIT", "20"))),
                    )
                    db_alerts = future.result(timeout=db_timeout) or []
            except FuturesTimeout:
                log.error("DB fetch timed out after %ss", db_timeout)
                log_security_event(event_type="db_alerts_fetch_failed", email=email, plan=plan_name, details=f"db timeout {db_timeout}s")
                db_alerts = []
            except Exception as e:
                log.error("DB fetch failed: %s", e)
                log_security_event(event_type="db_alerts_fetch_failed", email=email, plan=plan_name, details=str(e))
                db_alerts = []
        else:
            db_alerts = []

        count = len(db_alerts or [])
        db_elapsed = time.perf_counter() - db_start
        log.info("DB: fetched %d alerts (%.3fs)", count, db_elapsed)
        log_security_event(event_type="db_alerts_fetched", email=email, plan=plan_name, details=f"{count} alerts")
    except Exception as e:
        db_elapsed = time.perf_counter() - db_start
        log.error("DB fetch failed unexpectedly after %.3fs: %s", db_elapsed, e)
        usage_info["fallback_reason"] = "alert_fetch_error"
        log_security_event(event_type="db_alerts_fetch_failed", email=email, plan=plan_name, details=str(e))
        
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
        log.info("[HIST] %d historical for region=%s category=%s", len(historical_alerts), region, history_category)
    except Exception as e:
        log.warning("[HIST] fetch_past_incidents failed: %s", e)

    # ---------------- User profile ----------------
    user_profile: Dict[str, Any] = {}
    try:
        user_profile = fetch_user_profile(email) or {}
        # Merge with profile_data from main.py if provided
        if profile_data and isinstance(profile_data, dict):
            user_profile.update(profile_data)
        log.info("[PROFILE] Loaded profile for %s", email)
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

    # ----------- SMARTER NO-DATA / NO ALERTS GUARD -----------
    if not db_alerts:
        log.info("No alerts found for query='%s', region='%s', threat_type='%s'", query, region, threat_type)
        # Always call advisor (LLM) for best-effort situational summary even if no alerts in DB,
        # but protect with a timeout using a future. If the advisor times out and ASYNC_FALLBACK is enabled,
        # accept and queue a background job to finish processing and persist the result.
        advisor_kwargs = {
            "email": email,
            "region": region,
            "threat_type": threat_type,
            "user_profile": user_profile,
            "historical_alerts": historical_alerts,
        }
        ADVISOR_TIMEOUT = int(os.getenv("ADVISOR_TIMEOUT", "45"))
        ASYNC_FALLBACK = os.getenv("ASYNC_FALLBACK", "true").lower() in ("1", "true", "yes", "y")
        try:
            # run generate_advice(query, [], user_profile, **others) in a thread with timeout
            advisor_extra = dict(advisor_kwargs)
            user_prof = advisor_extra.pop("user_profile", None)
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(generate_advice, query, [], user_prof, **advisor_extra)
                try:
                    advisory_result = future.result(timeout=ADVISOR_TIMEOUT) or {}
                    advisory_result["no_alerts_found"] = True
                except FuturesTimeout:
                    log.error("Advisor (no-data fallback) timed out after %ss", ADVISOR_TIMEOUT)
                    usage_info["fallback_reason"] = "advisor_timeout"
                    log_security_event(event_type="advice_generation_timeout", email=email, plan=plan_name, details=f"{ADVISOR_TIMEOUT}s timeout")
                    if ASYNC_FALLBACK:
                        # spawn background job to finish processing and persist result
                        bg_session = session_id
                        start_background_job(bg_session, generate_advice, query, [], user_prof, **advisor_extra)
                        reply_text = "Accepted for background processing. Poll for results with session_id."
                        payload = {
                            "accepted": True,
                            "session_id": bg_session,
                            "message": reply_text,
                            "plan": plan_name,
                            "quota": _build_quota_obj(email, plan_name),
                        }
                        set_cache(cache_key, payload)
                        log_security_event(event_type="response_accepted_bg", email=email, plan=plan_name, details=f"bg_session={bg_session}")
                        return payload
                    else:
                        advisory_result = {"reply": "Request timed out. Please try a shorter or simpler query.", "timeout": True}
        except Exception as e:
            log.error("Advisor failed in no-alerts fallback: %s", e)
            advisory_result = {"reply": f"System error generating advice: {e}"}
            usage_info["fallback_reason"] = "advisor_error_no_alerts"
            log_security_event(event_type="advice_generation_failed", email=email, plan=plan_name, details=str(e))

        reply_text = advisory_result.get("reply", "No response generated.") if isinstance(advisory_result, dict) else str(advisory_result)
        
        quota_obj = _build_quota_obj(email, plan_name)
        
        payload = {
            "reply": reply_text,
            "plan": plan_name,
            "quota": quota_obj,
            "alerts": [],
            "usage": usage_info,
            "session_id": session_id,
            "no_data": True,
            "metadata": advisory_result if isinstance(advisory_result, dict) else {}
        }
        set_cache(cache_key, payload)
        log_security_event(event_type="response_sent", email=email, plan=plan_name, details=f"query={query[:120]}")
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
    try:
        advisor_extra = dict(advisor_kwargs)
        user_prof = advisor_extra.pop("user_profile", None)

        with ThreadPoolExecutor(max_workers=1) as ex:
            if db_alerts and (all_low or alerts_stale):
                log.info("[Proactive Mode] All alerts low or stale → proactive advisory")
                future = ex.submit(generate_advice, query, db_alerts, user_prof, **advisor_extra)
                try:
                    advisory_result = future.result(timeout=ADVISOR_TIMEOUT) or {}
                    advisory_result["proactive_triggered"] = True
                    usage_info["proactive_triggered"] = True
                except FuturesTimeout:
                    adv_elapsed = time.perf_counter() - advisor_start
                    log.error("Advisor timed out after %ss (proactive mode) [%.3fs elapsed]", ADVISOR_TIMEOUT, adv_elapsed)
                    usage_info["fallback_reason"] = "advisor_timeout"
                    log_security_event(event_type="advice_generation_timeout", email=email, plan=plan_name, details=f"{ADVISOR_TIMEOUT}s timeout")
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
                        log_security_event(event_type="response_accepted_bg", email=email, plan=plan_name, details=f"bg_session={bg_session}")
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
                    log_security_event(event_type="advice_generation_timeout", email=email, plan=plan_name, details=f"{ADVISOR_TIMEOUT}s timeout")
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
                        log_security_event(event_type="response_accepted_bg", email=email, plan=plan_name, details=f"bg_session={bg_session}")
                        return payload
                    else:
                        advisory_result = {"reply": "Request timed out. Please try a shorter or simpler query.", "timeout": True}
    except Exception as e:
        adv_elapsed = time.perf_counter() - advisor_start
        log.error("Advisor failed after %.3fs: %s", adv_elapsed, e)
        advisory_result = {"reply": f"System error generating advice: {e}"}
        usage_info["fallback_reason"] = "advisor_error"
        log_security_event(event_type="advice_generation_failed", email=email, plan=plan_name, details=str(e))

    advisor_elapsed = time.perf_counter() - advisor_start
    log.info("Advisor finished (%.3fs)", advisor_elapsed)

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

    log.info("Alerts processed: %d", len(results))
    log_security_event(event_type="alerts_processed", email=email, plan=plan_name, details=f"count={len(results)}")

    # Optional telemetry
    try:
        label_counts: Dict[str, int] = {}
        for a in results:
            lab = a.get("threat_label") or a.get("threat_level") or "Unknown"
            label_counts[lab] = label_counts.get(lab, 0) + 1
        log.info("[METRICS] label_counts=%s", label_counts)
        log_security_event(event_type="alerts_label_count", email=email, plan=plan_name, details=str(label_counts))
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
    log.info("handle_user_query completed in %.3fs", overall_elapsed)
    log_security_event(event_type="response_sent", email=email, plan=plan_name, details=f"query={query[:120]} elapsed={overall_elapsed:.3f}s")
    return payload