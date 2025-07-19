import json
import os
import time
import logging
import uuid
from dotenv import load_dotenv
from datetime import datetime
from hashlib import sha1

from db_utils import fetch_alerts_from_db
from threat_engine import summarize_alerts
from advisor import generate_advice
from plan_utils import get_plan, get_usage, check_user_message_quota

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

# --- Railway environment logging ---
RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
if RAILWAY_ENV:
    log.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    log.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

CACHE_TTL = 3600  # seconds (1 hour)
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
    if email and email != "anonymous":
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

    backend_plan = get_plan(email)
    plan = backend_plan.upper() if backend_plan and isinstance(backend_plan, str) else "FREE"
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
        return {"plan": plan, "usage": usage_info, "session_id": session_id}

    cache_key = sha1(json.dumps({
        "query": query,
        "region": region,
        "threat_type": threat_type,
        "session_id": session_id
    }, sort_keys=True).encode("utf-8")).hexdigest()
    log.info(f"handle_user_query: cache_key={cache_key}")

    cached = get_cache(cache_key)
    if cached is not None:
        log.info("handle_user_query: Returning cached response")
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
    except Exception as e:
        log.error(f"handle_user_query: Failed to fetch alerts from DB: {e}")
        usage_info["fallback_reason"] = "alert_fetch_error"
        return {
            "reply": f"System error fetching alerts: {e}",
            "plan": plan,
            "alerts": [],
            "usage": usage_info,
            "session_id": session_id
        }

    if not db_alerts:
        log.warning("[FALLBACK] No alerts available for query.")
        try:
            fallback = generate_advice(query, [], email=email, region=region, threat_type=threat_type)
            usage_info["fallback_reason"] = "no_alerts"
            log.info("handle_user_query: Fallback advice generated")
        except Exception as e:
            log.error(f"handle_user_query: Failed to generate fallback advice: {e}")
            fallback = f"System error generating advice: {e}"
            usage_info["fallback_reason"] = "advisor_error"
        result = {
            "reply": fallback,
            "plan": plan,
            "alerts": [],
            "usage": usage_info,
            "session_id": session_id
        }
        set_cache(cache_key, result)
        log.info("handle_user_query: Returning result after no alerts")
        return result

    try:
        log.info("handle_user_query: Calling summarize_alerts")
        summarized = summarize_alerts(db_alerts, user_email=email, session_id=session_id)
        log.info("handle_user_query: Summaries generated")
    except Exception as e:
        log.error(f"handle_user_query: Failed to summarize alerts: {e}")
        summarized = db_alerts
        usage_info["fallback_reason"] = "gpt_summarization_error"

    results = []
    log.info("handle_user_query: Building alert objects")
    for alert in summarized:
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
        if "label" not in alert_obj:
            alert_obj["label"] = alert_obj.get("threat_label", "Unknown")
        results.append(alert_obj)
    log.info(f"handle_user_query: Alerts processed: {len(results)}")

    label_counts = {}
    for a in results:
        label = a.get("threat_label", "Unknown")
        label_counts[label] = label_counts.get(label, 0) + 1
    log.info(f"[METRICS] Alert counts by label: {label_counts}")

    fallback = None
    try:
        log.info("handle_user_query: Calling generate_advice with alerts")
        fallback = generate_advice(query, db_alerts, email=email, region=region, threat_type=threat_type)
        log.info("handle_user_query: Fallback advice generated (final)")
    except Exception as e:
        log.error(f"handle_user_query: Failed to generate fallback advice (final): {e}")
        fallback = f"System error generating advice: {e}"
        usage_info["fallback_reason"] = "advisor_error"

    result = {
        "reply": fallback,
        "plan": plan,
        "alerts": results,
        "usage": usage_info,
        "session_id": session_id
    }
    set_cache(cache_key, result)
    log.info("handle_user_query: Returning final result")
    return result