import json
import os
import time
import logging
import uuid
from dotenv import load_dotenv
from datetime import datetime, timedelta
from hashlib import sha1

from db_utils import fetch_alerts_from_db, fetch_past_incidents, fetch_user_profile  # <-- Updated import
from threat_engine import summarize_alerts
from advisor import generate_advice
from plan_utils import get_plan, get_usage, check_user_message_quota, require_plan_feature
from security_log_utils import log_security_event

try:
    from city_utils import fuzzy_match_city, normalize_city
except ImportError:
    fuzzy_match_city = None
    normalize_city = None

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

CACHE_TTL = 3600
RESPONSE_CACHE = {}

def set_cache(key, value):
    RESPONSE_CACHE[key] = (value, time.time())

def get_cache(key):
    entry = RESPONSE_CACHE.get(key)
    if not entry:
        return None
    value, timestamp = entry
    if time.time() - timestamp > CACHE_TTL:
        del RESPONSE_CACHE[key]
        return None
    return value

load_dotenv()

def json_default(obj):
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

def normalize_value(val, default="All"):
    if isinstance(val, str):
        val = val.strip()
        if not val or val.lower() in ["all", "all regions", "all threats"]:
            return default
        return val
    return default

def normalize_region(region, city_list=None):
    if not region or region.lower() in ["all", "all regions"]:
        return None
    if fuzzy_match_city and city_list:
        match = fuzzy_match_city(region, city_list)
        return match if match else region
    if normalize_city:
        return normalize_city(region)
    return region

def get_or_generate_session_id(email, body=None):
    if body and "session_id" in body and body["session_id"]:
        return body["session_id"]
    if email:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, email.lower()))
    return str(uuid.uuid4())

def ensure_str(val):
    return "" if val is None else str(val)

def ensure_num(val, default=0):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def ensure_label(val):
    if not val:
        return "Unknown"
    s = str(val).strip()
    return s if s else "Unknown"

def ensure_date(alert):
    for key in ["date", "timestamp", "pubDate", "published_at", "published"]:
        if key in alert and alert[key]:
            try:
                dt = alert[key]
                if isinstance(dt, datetime):
                    return dt.isoformat()
                if isinstance(dt, (int, float)):
                    return datetime.utcfromtimestamp(dt).isoformat()
                dtstr = str(dt).strip()
                try:
                    return datetime.fromisoformat(dtstr).isoformat()
                except Exception:
                    pass
                return dtstr
            except Exception:
                continue
    return ""

def handle_user_query(message, email, region=None, threat_type=None, city_list=None, body=None):
    log.info("handle_user_query: ENTERED")
    log.info(f"Received query: {message} | Email: {email}")

    if not email:
        log_security_event(
            event_type="missing_email",
            details="handle_user_query called without email"
        )
        raise ValueError("handle_user_query requires a valid authenticated user email.")

    backend_plan = get_plan(email)
    plan = backend_plan.upper() if backend_plan and isinstance(backend_plan, str) else "FREE"
    if not require_plan_feature(email, "insights") and plan == "FREE":
        log.info(f"User {email} on plan '{plan}' does not have advisory/insights feature. Returning limited response.")
        usage_info = get_usage(email)
        log_security_event(
            event_type="plan_feature_denied",
            email=email,
            plan=plan,
            details="Advisory/insights feature denied for this plan"
        )
        return {
            "reply": "Your current plan does not allow advanced advisory features. Please upgrade to access full alerts and intelligence.",
            "plan": plan,
            "alerts": [],
            "usage": usage_info,
            "session_id": get_or_generate_session_id(email, body)
        }

    plan_limits = get_plan(plan)
    log.info(f"Plan: {plan}")

    query = message.get("query", "") if isinstance(message, dict) else str(message)
    log.info(f"Query content: {query}")

    region = normalize_value(region)
    threat_type = normalize_value(threat_type)
    region = None if region.lower() == "all" else region
    threat_type = None if threat_type.lower() == "all" else threat_type
    if region and city_list:
        region = normalize_region(region, city_list)
    log.debug(f"region={region!r}, threat_type={threat_type!r}")

    session_id = get_or_generate_session_id(email, body)
    usage_info = get_usage(email)

    if isinstance(query, str) and query.lower().strip() in ["status", "plan"]:
        log.info("handle_user_query: STATUS/PLAN shortcut")
        log_security_event(
            event_type="status_plan_query",
            email=email,
            plan=plan,
            details="Shortcut query for status/plan"
        )
        return {"plan": plan, "usage": usage_info, "session_id": session_id}

    cache_key = sha1(json.dumps({
        "query": query,
        "region": region,
        "threat_type": threat_type,
        "session_id": session_id
    }, sort_keys=True, default=json_default).encode("utf-8")).hexdigest()
    log.info(f"handle_user_query: cache_key={cache_key}")

    cached = get_cache(cache_key)
    if cached is not None:
        log.info("handle_user_query: Returning cached response")
        log_security_event(
            event_type="cache_hit",
            email=email,
            plan=plan,
            details=f"Cache key: {cache_key}"
        )
        return cached

    # --- ALERT FETCH FROM DB ---
    try:
        log.info("handle_user_query: Calling fetch_alerts_from_db")
        db_alerts = fetch_alerts_from_db(
            region=region,
            threat_level=threat_type,
            limit=20
        )
        log.info(f"handle_user_query: Alerts fetched from DB: {len(db_alerts)}")
        log_security_event(
            event_type="db_alerts_fetched",
            email=email,
            plan=plan,
            details=f"Fetched {len(db_alerts)} alerts"
        )
    except Exception as e:
        log.error(f"handle_user_query: Failed to fetch alerts from DB: {e}")
        usage_info["fallback_reason"] = "alert_fetch_error"
        log_security_event(
            event_type="db_alerts_fetch_failed",
            email=email,
            plan=plan,
            details=str(e)
        )
        return {
            "reply": f"System error fetching alerts: {e}",
            "plan": plan,
            "alerts": [],
            "usage": usage_info,
            "session_id": session_id
        }

    # --- Historical Context: Fetch last 90 days of similar alerts for this region/category ---
    historical_alerts = []
    categories = []
    if db_alerts:
        categories = list(set(a.get("category") for a in db_alerts if a.get("category")))
    history_category = categories[0] if categories else None
    try:
        historical_alerts = fetch_past_incidents(region=region, category=history_category, days=90, limit=100)
        log.info(f"[HISTORICAL] Fetched {len(historical_alerts)} historical alerts for region={region}, category={history_category}")
    except Exception as e:
        log.warning(f"[HISTORICAL] Error fetching historical alerts: {e}")

    # --- User Profile Injection ---
    user_profile = None
    try:
        user_profile = fetch_user_profile(email)
        log.info(f"[USER_PROFILE] Loaded for {email}: {user_profile}")
    except Exception as e:
        log.warning(f"[USER_PROFILE] Could not load profile for {email}: {e}")
        user_profile = {}

    # --- Proactive Mode Trigger ---
    all_low = all(a.get("score", 0) < 55 for a in db_alerts) if db_alerts else False
    alerts_stale = False
    if db_alerts:
        most_recent_date = max([ensure_date(a) for a in db_alerts if ensure_date(a)], default=None)
        if most_recent_date:
            try:
                dt = datetime.fromisoformat(most_recent_date)
                alerts_stale = (datetime.utcnow() - dt).days >= 7
            except Exception:
                alerts_stale = False

    # Always pass historical_alerts and user_profile to generate_advice!
    advisory_result = None
    try:
        advisor_kwargs = {
            "email": email,
            "region": region,
            "threat_type": threat_type,
            "user_profile": user_profile,  # <-- Pass user profile
        }
        if db_alerts and (all_low or alerts_stale):
            log.info("[Proactive Mode] All alerts low or stale; triggering proactive advisory.")
            advisory_result = generate_advice(query, db_alerts, **advisor_kwargs)
            advisory_result["proactive_triggered"] = True
            usage_info["proactive_triggered"] = True
        else:
            advisory_result = generate_advice(query, db_alerts, **advisor_kwargs)
            advisory_result["proactive_triggered"] = False
    except Exception as e:
        log.error(f"handle_user_query: Failed to generate advisory: {e}")
        advisory_result = {"reply": f"System error generating advice: {e}"}
        usage_info["fallback_reason"] = "advisor_error"
        log_security_event(
            event_type="advice_generation_failed",
            email=email,
            plan=plan,
            details=str(e)
        )

    results = []
    log.info("handle_user_query: Building alert objects")
    for alert in db_alerts:
        alert_obj = {
            "title": ensure_str(alert.get("title", "")),
            "summary": ensure_str(alert.get("gpt_summary") or alert.get("summary", "")),
            "link": ensure_str(alert.get("link", "")),
            "source": ensure_str(alert.get("source", "")),
            "category": ensure_str(alert.get("category", alert.get("type", ""))),
            "subcategory": ensure_str(alert.get("subcategory", "")),
            "threat_label": ensure_label(alert.get("threat_label", alert.get("level", ""))),
            "threat_score": ensure_num(alert.get("threat_score", alert.get("score", ""))),
            "confidence": ensure_num(alert.get("confidence", "")),
            "date": ensure_date(alert),
            "city": ensure_str(alert.get("city", "")),
            "country": ensure_str(alert.get("country", "")),
            "reasoning": ensure_str(alert.get("reasoning", "")),
            "severity": ensure_label(alert.get("level", alert.get("threat_label", ""))),
            "gpt_summary": ensure_str(alert.get("gpt_summary", "")),
            "forecast": ensure_str(alert.get("forecast", "")),
            "historical_context": ensure_str(alert.get("historical_context", "")),
            "sentiment": ensure_str(alert.get("sentiment", "")),
            "legal_risk": ensure_str(alert.get("legal_risk", "")),
            "inclusion_info": ensure_str(alert.get("inclusion_info", "")),
            "profession_info": ensure_str(alert.get("profession_info", "")),
        }
        alert_obj["label"] = alert.get("label", alert.get("threat_label", "Unknown"))
        results.append(alert_obj)
    log.info(f"handle_user_query: Alerts processed: {len(results)}")
    log_security_event(
        event_type="alerts_processed",
        email=email,
        plan=plan,
        details=f"Processed {len(results)} alerts"
    )

    label_counts = {}
    for a in results:
        label = a.get("label", a.get("threat_label", "Unknown"))
        label_counts[label] = label_counts.get(label, 0) + 1
    log.info(f"[METRICS] Alert counts by label: {label_counts}")
    log_security_event(
        event_type="alerts_label_count",
        email=email,
        plan=plan,
        details=f"Label counts: {label_counts}"
    )

    result = {
        "reply": advisory_result,
        "plan": plan,
        "alerts": results,
        "usage": usage_info,
        "session_id": session_id
    }
    set_cache(cache_key, result)
    log.info("handle_user_query: Returning final result")
    log_security_event(
        event_type="response_sent",
        email=email,
        plan=plan,
        details=f"Final response for query: {query}"
    )
    return result