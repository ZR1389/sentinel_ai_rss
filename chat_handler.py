import json
import os
import time
import logging
from dotenv import load_dotenv
from datetime import datetime
from hashlib import sha1

from rss_processor import get_clean_alerts
from threat_engine import summarize_alerts
from advisor import generate_advice
from clients import get_plan

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

USAGE_FILE = "usage_log.json"
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

PLAN_LIMITS = {
    "FREE": {"chat_limit": 3},
    "BASIC": {"chat_limit": 100},
    "PRO": {"chat_limit": 500},
    "VIP": {"chat_limit": None},
}

def load_usage_data():
    if not os.path.exists(USAGE_FILE):
        return {}
    with open(USAGE_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_usage_data(data):
    with open(USAGE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def check_usage_allowed(email, plan):
    usage_data = load_usage_data()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    usage_today = usage_data.get(email, {}).get(today, 0)
    limit = PLAN_LIMITS.get(plan, {}).get("chat_limit")
    return usage_today < limit if limit is not None else True

def increment_usage(email):
    usage_data = load_usage_data()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if email not in usage_data:
        usage_data[email] = {}
    if today not in usage_data[email]:
        usage_data[email][today] = 0
    usage_data[email][today] += 1
    save_usage_data(usage_data)

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

def handle_user_query(message, email, region=None, threat_type=None, plan=None, city_list=None):
    log.info(f"Received query: {message} | Email: {email}")

    backend_plan = get_plan(email)
    plan = backend_plan.upper() if backend_plan and isinstance(backend_plan, str) else "FREE"
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

    if isinstance(query, str) and query.lower().strip() in ["status", "plan"]:
        return {"plan": plan}

    if not check_usage_allowed(email, plan):
        log.warning("Usage limit reached")
        return {
            "reply": "You reached your monthly message quota. Please upgrade to get more access.",
            "plan": plan,
            "alerts": []
        }

    increment_usage(email)
    log.info("Usage incremented")

    cache_key = sha1(json.dumps({
        "query": query,
        "region": region,
        "threat_type": threat_type,
        "plan": plan
    }, sort_keys=True).encode("utf-8")).hexdigest()

    cached = get_cache(cache_key)
    if cached is not None:
        log.info("Returning cached response")
        return cached

    try:
        raw_alerts = get_clean_alerts(region=region, topic=threat_type, summarize=True, plan=plan)
        log.info(f"Alerts fetched: {len(raw_alerts)}")
    except Exception as e:
        log.error(f"Failed to fetch alerts: {e}")
        return {
            "reply": f"System error fetching alerts: {e}",
            "plan": plan,
            "alerts": []
        }

    if not raw_alerts:
        try:
            fallback = generate_advice(query, [], email=email, region=region, threat_type=threat_type)
        except Exception as e:
            log.error(f"Failed to generate advice: {e}")
            fallback = f"System error generating advice: {e}"
        result = {
            "reply": fallback,
            "plan": plan,
            "alerts": []
        }
        set_cache(cache_key, result)
        return result

    try:
        summarized = summarize_alerts(raw_alerts)
        log.info("Summaries generated")
    except Exception as e:
        log.error(f"Failed to summarize alerts: {e}")
        summarized = raw_alerts

    results = []
    for alert in summarized:
        summary = alert.get("gpt_summary") or alert.get("summary", "")
        results.append({
            "title": alert.get("title", ""),
            "summary": summary,
            "link": alert.get("link", ""),
            "source": alert.get("source", ""),
            "type": alert.get("type", ""),
            "threat_label": alert.get("threat_label", ""),
            "threat_score": alert.get("score", ""),
            "confidence": alert.get("confidence", ""),
            "reasoning": alert.get("reasoning", ""),
            "category": alert.get("category", ""),
            "subcategory": alert.get("subcategory", ""),
            "gpt_summary": alert.get("gpt_summary", ""),
            "severity": alert.get("level", ""),
            "country": alert.get("country", ""),
            "city": alert.get("city", "")
        })

    label_counts = {}
    for a in results:
        label = a.get("threat_label", "Unknown")
        label_counts[label] = label_counts.get(label, 0) + 1
    log.info(f"[METRICS] Alert counts by label: {label_counts}")

    try:
        fallback = generate_advice(query, raw_alerts, email=email, region=region, threat_type=threat_type)
        log.info("Fallback advice generated")
    except Exception as e:
        log.error(f"Failed to generate fallback advice: {e}")
        fallback = f"System error generating advice: {e}"

    result = {
        "reply": fallback,
        "plan": plan,
        "alerts": results
    }
    set_cache(cache_key, result)
    return result