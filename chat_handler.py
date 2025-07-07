import json
import os
import time
from dotenv import load_dotenv
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from rss_processor import get_clean_alerts
from threat_scorer import assess_threat_level
from threat_engine import summarize_alerts
from advisor import generate_advice
from clients import get_plan

USAGE_FILE = "usage_log.json"
RESPONSE_CACHE = {}

load_dotenv()

with open("risk_profiles.json", "r") as f:
    risk_profiles = json.load(f)

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
    """Ensure value is a clean string for backend logic."""
    if isinstance(val, str):
        val = val.strip()
        if not val or val.lower() in ["all", "all regions", "all threats"]:
            return default
        return val
    return default

def smart_risk_profile_fallback(region, lang="en", original_query=None):
    """
    Try to find a region profile, fallback to 'All', fallback to English, fallback to generic.
    """
    # Try exact match
    region_data = risk_profiles.get(region)
    if not region_data:
        # Try case-insensitive match
        for r in risk_profiles:
            if r.lower() == region.lower():
                region_data = risk_profiles[r]
                break
    if not region_data:
        region_data = risk_profiles.get("All", {})
    # Try lang, then English, then generic
    return (
        (region_data.get(lang) or region_data.get("en"))
        or "No alerts right now. Stay aware and consult regional sources."
    )

def handle_user_query(message, email, lang="en", region=None, threat_type=None, plan=None):
    print(f"Received query: {message} | Email: {email} | Lang: {lang}")

    plan_raw = get_plan(email) or plan or "Free"
    plan = plan_raw.upper() if isinstance(plan_raw, str) else "FREE"
    print(f"Plan: {plan}")

    query = message.get("query", "") if isinstance(message, dict) else str(message)
    print(f"Query content: {query}")

    # Sanitize and normalize all user-facing values
    lang = lang if isinstance(lang, str) else "en"
    # PATCH: region and threat_type set to None if blank/All for advisor.py compatibility
    region = normalize_value(region)
    threat_type = normalize_value(threat_type)
    region = None if region.lower() == "all" else region
    threat_type = None if threat_type.lower() == "all" else threat_type
    print(f"[DEBUG] region={region!r}, threat_type={threat_type!r}")

    if isinstance(query, str) and query.lower().strip() in ["status", "plan"]:
        return {"plan": plan}

    if not check_usage_allowed(email, plan):
        print("Usage limit reached")
        return {
            "reply": "You reached your monthly message quota. Please upgrade to get more access.",
            "plan": plan,
            "alerts": []
        }

    increment_usage(email)
    print("Usage incremented")

    cache_key = f"{query}_{lang}_{region}_{threat_type}_{plan}"
    if cache_key in RESPONSE_CACHE:
        print("Returning cached response")
        return RESPONSE_CACHE[cache_key]

    # Fetch alerts
    raw_alerts = get_clean_alerts(region=region, topic=threat_type, summarize=True)
    print(f"Alerts fetched: {len(raw_alerts)}")

    # SMART FALLBACK: handle all cases when no alerts exist
    if not raw_alerts:
        # Use advisor.py's logic for all plans, including static and GPT fallback
        fallback = generate_advice(query, [], email=email, region=region, threat_type=threat_type)
        result = {
            "reply": fallback,
            "plan": plan,
            "alerts": []
        }
        RESPONSE_CACHE[cache_key] = result
        return result

    # Threat scoring in parallel
    with ThreadPoolExecutor(max_workers=5) as executor:
        threat_scores = list(executor.map(assess_threat_level, raw_alerts))

    # Summarize alerts
    summarized = summarize_alerts(raw_alerts, lang=lang)
    print("Summaries generated")

    results = []
    for i, alert in enumerate(summarized):
        alert_type = alert.get("type", "")
        if not isinstance(alert_type, str):
            alert_type = str(alert_type)
        results.append({
            "title": alert.get("title", ""),
            "summary": alert.get("summary", ""),
            "link": alert.get("link", ""),
            "source": alert.get("source", ""),
            "type": alert_type,
            "level": threat_scores[i] if i < len(threat_scores) else None,
            "gpt_summary": alert.get("gpt_summary", "")
        })

    # Always generate advice for the UI (for sidebar, etc)
    fallback = generate_advice(query, raw_alerts, lang=lang, email=email, region=region, threat_type=threat_type)
    print("Fallback advice generated")

    result = {
        "reply": fallback,
        "plan": plan,
        "alerts": results
    }
    RESPONSE_CACHE[cache_key] = result
    return result