import os
import re
import json
import asyncio
import httpx
import feedparser
from datetime import datetime, timezone
from urllib.parse import urlparse
from dotenv import load_dotenv
from hashlib import sha256
from pathlib import Path
from unidecode import unidecode
import difflib
from langdetect import detect

from db_utils import save_raw_alerts_to_db, fetch_incident_clusters, save_user_threat_preferences, fetch_user_threat_preferences
from feeds_catalog import LOCAL_FEEDS, COUNTRY_FEEDS, GLOBAL_FEEDS

with open('fcdo_country_feeds.json', 'r', encoding='utf-8') as f:
    FCDO_FEEDS = json.load(f)

with open('threat_keywords.json', 'r', encoding='utf-8') as f:
    keywords_data = json.load(f)
    THREAT_KEYWORDS = keywords_data["keywords"]
    TRANSLATED_KEYWORDS = keywords_data["translated"]

load_dotenv()

from telegram_scraper import scrape_telegram_messages
from translation_utils import translate_snippet

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
if RAILWAY_ENV:
    logger.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    logger.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

def json_default(obj):
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

KEYWORD_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in THREAT_KEYWORDS) + r')\b',
    re.IGNORECASE
)

def first_sentence(text):
    sentences = re.split(r'(?<=[.!?。！？\n])\s+', text.strip())
    return sentences[0] if sentences else text

def any_multilingual_keyword(text, lang, TRANSLATED_KEYWORDS):
    text = text.lower()
    for threat, lang_map in TRANSLATED_KEYWORDS.items():
        roots = lang_map.get(lang, [])
        for root in roots:
            if root in text:
                return threat
    return None

def safe_detect_lang(text, default="en"):
    try:
        if len(text.strip()) < 10:
            return default
        return detect(text)
    except Exception:
        return default

NORMALIZED_LOCAL_FEEDS = {unidecode(city).lower().strip(): v for city, v in LOCAL_FEEDS.items()}

def get_feed_for_city(city):
    if not city:
        return None
    city_key = unidecode(city).lower().strip()
    match = difflib.get_close_matches(city_key, NORMALIZED_LOCAL_FEEDS.keys(), n=1, cutoff=0.8)
    if match:
        return NORMALIZED_LOCAL_FEEDS[match[0]]
    return None

def get_feed_for_location(region=None, city=None, topic=None):
    region_key = region.strip().title() if region else None
    city_feeds = get_feed_for_city(city)
    if city_feeds:
        logger.info("Using LOCAL feed(s) for city match.")
        return city_feeds
    if region_key and region_key in FCDO_FEEDS:
        logger.info("Using FCDO region feed.")
        return [FCDO_FEEDS[region_key]]
    if topic and topic.lower() == "cyber":
        try:
            from feeds_catalog import CYBER_FEEDS
            return CYBER_FEEDS
        except ImportError:
            pass
    region_key_lower = region.lower().strip() if region else None
    if region_key_lower and region_key_lower in COUNTRY_FEEDS:
        logger.info("Using COUNTRY feed.")
        return COUNTRY_FEEDS[region_key_lower]
    logger.info("Using GLOBAL feed(s) as fallback.")
    return GLOBAL_FEEDS

def normalize_timestamp(ts):
    """Normalize timestamp to UTC ISO string."""
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        else:
            ts = ts.astimezone(timezone.utc)
        return ts.isoformat()
    if isinstance(ts, (int, float)):
        return datetime.utcfromtimestamp(ts).replace(tzinfo=timezone.utc).isoformat()
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.isoformat()
        except Exception:
            try:
                import email.utils
                parsed = email.utils.parsedate_to_datetime(ts)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                else:
                    parsed = parsed.astimezone(timezone.utc)
                return parsed.isoformat()
            except Exception:
                return ts
    return None

def generate_series_id(region, threat_type, timestamp):
    """Generate a series_id for related incidents in the same region/type/time window."""
    if not region:
        region = "unknown"
    if not threat_type:
        threat_type = "unknown"
    try:
        if isinstance(timestamp, str):
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        elif isinstance(timestamp, datetime):
            dt = timestamp
        else:
            dt = datetime.utcnow()
        day_str = dt.strftime("%Y-%m-%d")
    except Exception:
        day_str = "unknown"
    base = f"{region.lower().strip()}|{threat_type.lower().strip()}|{day_str}"
    return sha256(base.encode("utf-8")).hexdigest()

def extract_keywords(text):
    raw_matches = []
    normalized_matches = []
    text_lower = text.lower()
    for k in THREAT_KEYWORDS:
        if re.search(rf'\b{re.escape(k)}\b', text_lower):
            raw_matches.append(k)
    normalized_matches = [k.lower() for k in raw_matches]
    return raw_matches, normalized_matches

# ---- CATEGORY AND SUBCATEGORY EXTRACTION ----
def extract_threat_category(text):
    """
    Extracts the main threat category from text.
    Returns (category, confidence).
    """
    if not text:
        return "Other", 0.5
    text_lower = text.lower()
    categories = [
        "Crime", "Terrorism", "Civil Unrest", "Cyber", "Infrastructure",
        "Environmental", "Epidemic", "Other"
    ]
    for cat in categories:
        if cat.lower() in text_lower:
            return cat, 0.90
    # Fallback: keyword matching
    for k in THREAT_KEYWORDS:
        if re.search(rf'\b{re.escape(k)}\b', text_lower):
            # crude mapping, can extend with keyword-category map
            if "cyber" in k or "malware" in k or "ransomware" in k:
                return "Cyber", 0.7
            if "disease" in k or "pandemic" in k or "epidemic" in k:
                return "Epidemic", 0.7
            if "riot" in k or "protest" in k or "unrest" in k:
                return "Civil Unrest", 0.7
            if "bomb" in k or "attack" in k or "terror" in k:
                return "Terrorism", 0.7
            if "earthquake" in k or "flood" in k or "wild fire" in k:
                return "Environmental", 0.7
            if "crime" in k or "shooting" in k or "kidnapping" in k:
                return "Crime", 0.7
    return "Other", 0.5

def extract_threat_subcategory(text, category):
    """
    Extracts subcategory from text, using category context.
    Returns subcategory string.
    """
    if not text or not category:
        return "Unspecified"
    text_lower = text.lower()
    if category == "Cyber":
        for sub in ["ransomware", "data breach", "phishing", "malware", "hacktivism"]:
            if sub in text_lower:
                return sub.title()
    if category == "Terrorism":
        for sub in ["bombing", "suicide bombing", "attack", "IED", "hostage"]:
            if sub in text_lower:
                return sub.title()
    if category == "Crime":
        for sub in ["shooting", "kidnapping", "hijacking", "abduction", "assassination"]:
            if sub in text_lower:
                return sub.title()
    if category == "Civil Unrest":
        for sub in ["protest", "riot", "coup", "martial law", "uprising"]:
            if sub in text_lower:
                return sub.title()
    if category == "Environmental":
        for sub in ["earthquake", "flood", "wild fire", "hurricane", "tornado"]:
            if sub in text_lower:
                return sub.title()
    if category == "Epidemic":
        for sub in ["pandemic", "viral outbreak", "disease spread", "quarantine"]:
            if sub in text_lower:
                return sub.title()
    return "Unspecified"

async def fetch_feed_async(url, timeout=7, retries=3, backoff=1.5, max_backoff=60):
    attempt = 0
    current_backoff = backoff
    while attempt < retries:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=timeout)
                if response.status_code == 200:
                    logger.info(f"✅ Fetched: {url}")
                    return feedparser.parse(response.text), url
                elif response.status_code in [429, 503]:
                    current_backoff = min(current_backoff * 2, max_backoff)
                    logger.warning(f"⚠️ Throttled ({response.status_code}) by {url}; backing off for {current_backoff} seconds")
                    await asyncio.sleep(current_backoff)
                else:
                    logger.warning(f"⚠️ Feed returned {response.status_code}: {url}")
        except Exception as e:
            logger.warning(f"❌ Attempt {attempt + 1} failed for {url} — {e}")
        attempt += 1
        await asyncio.sleep(current_backoff)
    logger.warning(f"❌ Failed to fetch after {retries} retries: {url}")
    return None, url

# ---- Shared Keyword Scoring ----
def compute_keyword_weight(text, return_detail=False):
    score = 0
    matched = []
    text_lower = text.lower()
    for k in THREAT_KEYWORDS:
        if re.search(rf'\b{k}\b', text_lower, re.IGNORECASE):
            score += 1
            matched.append(k)
    if return_detail:
        return score, matched
    return score

# ---- Shared Enrichment Logging ----
def enrich_log(alert, region=None, city=None, source=None, user_email=None, log_path=None):
    if os.getenv("LOG_ALERTS", "true").lower() != "true":
        return
    if log_path is None:
        log_path = os.getenv("ENRICH_LOG_PATH", "logs/alert_enrichments.jsonl")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    enrich_record = {
        "timestamp": datetime.utcnow().isoformat(),
        "region": region if region else alert.get('region'),
        "city": city if city else alert.get('city'),
        "source": source if source else alert.get('source'),
        "user_email": user_email,
        "alert": alert
    }
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(enrich_record, ensure_ascii=False, default=json_default) + "\n")
    except Exception as e:
        logger.error(f"[enrich_log][FileError] {e}")

# ---- Fallback Routes/Cities for Alternatives ----
FALLBACK_ROUTES = {
    "Kyiv": [
        {"route": "Via Lviv", "city": "Lviv", "description": "Safer route via western Ukraine."},
        {"route": "Via Dnipro", "city": "Dnipro", "description": "Alternate route avoiding central conflict zones."},
    ],
    "Mexico City": [
        {"route": "Via Puebla", "city": "Puebla", "description": "Recommended alternate for unrest in CDMX."},
    ],
    # Add more as needed...
}

# ---- Trend Metrics Helper ----
def compute_trend_metrics(historical_alerts):
    trend_direction = compute_trend_direction(historical_alerts)
    future_risk_probability = compute_future_risk_probability(historical_alerts)
    early_warning_indicators = extract_early_warning_indicators(historical_alerts)
    return {
        "trend_direction": trend_direction,
        "future_risk_probability": future_risk_probability,
        "early_warning_indicators": early_warning_indicators
    }

def compute_trend_direction(alerts):
    if len(alerts) < 3:
        return "unknown"
    scores = [a.get("score", 0) for a in alerts if isinstance(a.get("score", 0), (int, float))]
    if len(scores) < 3:
        return "unknown"
    mid = len(scores) // 2
    before = scores[mid:]
    after = scores[:mid]
    if not after or not before:
        return "unknown"
    before_avg = sum(before) / len(before)
    after_avg = sum(after) / len(after)
    if after_avg > before_avg + 7:
        return "deteriorating"
    elif after_avg < before_avg - 7:
        return "improving"
    else:
        return "stable"

def compute_future_risk_probability(alerts, window=3):
    if len(alerts) < window + 1:
        return 0.5
    sorted_alerts = sorted(alerts, key=lambda x: x.get("timestamp", ""), reverse=True)
    scores = [a.get("score", 0) for a in sorted_alerts if isinstance(a.get("score", 0), (int, float))]
    if len(scores) < window * 2:
        return 0.5
    recent = scores[:window]
    previous = scores[window:window*2]
    if not previous or not recent:
        return 0.5
    diff = (sum(recent)/len(recent)) - (sum(previous)/len(previous))
    if diff > 10:
        return 0.9
    if diff > 5:
        return 0.7
    if diff < -10:
        return 0.1
    if diff < -5:
        return 0.3
    return 0.5

def extract_early_warning_indicators(alerts):
    indicators = set()
    for alert in alerts:
        if alert.get("score", 0) >= 75:
            for k in alert.get("matched_keywords", []):
                indicators.add(k)
            if "subcategory" in alert and alert["subcategory"]:
                indicators.add(alert["subcategory"])
            if "tags" in alert and alert["tags"]:
                indicators.update(alert["tags"])
            if "processed_keywords" in alert and alert["processed_keywords"]:
                indicators.update(alert["processed_keywords"])
    return list(indicators)

def run_sentiment_analysis(text):
    try:
        from xai_client import grok_chat
        from prompts import SENTIMENT_ANALYSIS_PROMPT
        prompt = SENTIMENT_ANALYSIS_PROMPT.format(incident=text)
        messages = [{"role": "system", "content": ""}, {"role": "user", "content": prompt}]
        return grok_chat(messages, temperature=0.2, max_tokens=60)
    except Exception as e:
        logger.error(f"[SentimentAnalysisError] {e}")
        return f"[SentimentAnalysisError] {e}"

def run_forecast(region, input_data, user_message=None):
    try:
        from xai_client import grok_chat
        from prompts import PROACTIVE_FORECAST_PROMPT
        prompt = PROACTIVE_FORECAST_PROMPT.format(region=region, input_data=json.dumps(input_data, default=json_default), user_message=user_message)
        messages = [{"role": "system", "content": ""}, {"role": "user", "content": prompt}]
        return grok_chat(messages, temperature=0.2, max_tokens=80)
    except Exception as e:
        logger.error(f"[ForecastError] {e}")
        return f"[ForecastError] {e}"

def run_legal_risk(text, region):
    try:
        from xai_client import grok_chat
        from prompts import LEGAL_REGULATORY_RISK_PROMPT
        prompt = LEGAL_REGULATORY_RISK_PROMPT.format(incident=text, region=region)
        messages = [{"role": "system", "content": ""}, {"role": "user", "content": prompt}]
        return grok_chat(messages, temperature=0.2, max_tokens=80)
    except Exception as e:
        logger.error(f"[LegalRiskError] {e}")
        return f"[LegalRiskError] {e}"

def run_cyber_ot_risk(text, region):
    try:
        from xai_client import grok_chat
        from prompts import CYBER_OT_RISK_PROMPT
        prompt = CYBER_OT_RISK_PROMPT.format(incident=text, region=region)
        messages = [{"role": "system", "content": ""}, {"role": "user", "content": prompt}]
        return grok_chat(messages, temperature=0.2, max_tokens=80)
    except Exception as e:
        logger.error(f"[CyberOTRiskError] {e}")
        return f"[CyberOTRiskError] {e}"

def run_environmental_epidemic_risk(text, region):
    try:
        from xai_client import grok_chat
        from prompts import ENVIRONMENTAL_EPIDEMIC_RISK_PROMPT
        prompt = ENVIRONMENTAL_EPIDEMIC_RISK_PROMPT.format(incident=text, region=region)
        messages = [{"role": "system", "content": ""}, {"role": "user", "content": prompt}]
        return grok_chat(messages, temperature=0.2, max_tokens=80)
    except Exception as e:
        logger.error(f"[EnvEpidemicRiskError] {e}")
        return f"[EnvEpidemicRiskError] {e}"

def assign_incident_cluster_ids(alerts, region=None, keywords=None, hours_window=72):
    clusters = fetch_incident_clusters(region=region, keywords=keywords, hours_window=hours_window)
    uuid_to_cluster = {}
    for cl in clusters:
        for uuid in cl["alert_uuids"]:
            uuid_to_cluster[uuid] = f"{cl['region']}-{cl['keywords']}-{cl['start_time']}"
    for alert in alerts:
        alert_uuid = alert.get("uuid")
        if alert_uuid in uuid_to_cluster:
            alert["incident_cluster_id"] = uuid_to_cluster[alert_uuid]
        else:
            alert["incident_cluster_id"] = None
    return alerts

def tag_alerts_by_user_interest(alerts, email):
    prefs = fetch_user_threat_preferences(email)
    tagged_alerts = []
    for alert in alerts:
        score = 0
        for field in ["regions", "categories", "keywords"]:
            tags = alert.get("tags", [])
            pref_vals = prefs.get(field) or []
            if isinstance(pref_vals, str):
                pref_vals = [pref_vals]
            if any(x in tags for x in pref_vals):
                score += 1
        alert["user_interest_tag"] = score
        tagged_alerts.append(alert)
    return tagged_alerts