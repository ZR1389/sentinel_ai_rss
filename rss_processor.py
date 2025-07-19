import os
import re
import time
import json
import asyncio
import httpx
import feedparser
from datetime import datetime, timedelta
from urllib.parse import urlparse
from dotenv import load_dotenv
from hashlib import sha256
from pathlib import Path
from unidecode import unidecode
import difflib
from langdetect import detect

from db_utils import save_alerts_to_db
from feeds_catalog import LOCAL_FEEDS, COUNTRY_FEEDS, GLOBAL_FEEDS

# --- SHARED ENRICHMENT IMPORTS ---
from risk_shared import (
    compute_keyword_weight,
    enrich_log,
    run_sentiment_analysis,
    run_forecast,
    run_legal_risk,
    run_cyber_ot_risk,
    run_environmental_epidemic_risk,
    KEYWORD_WEIGHTS
)

with open('fcdo_country_feeds.json', 'r', encoding='utf-8') as f:
    FCDO_FEEDS = json.load(f)

with open('threat_keywords.json', 'r', encoding='utf-8') as f:
    keywords_data = json.load(f)
    THREAT_KEYWORDS = keywords_data["keywords"]
    TRANSLATED_KEYWORDS = keywords_data["translated"]

load_dotenv()

from telegram_scraper import scrape_telegram_messages
from xai_client import grok_chat
from openai import OpenAI
from threat_scorer import assess_threat_level
from prompts import (
    SYSTEM_PROMPT, TYPE_PROMPT, FALLBACK_PROMPT, SECURITY_SUMMARIZE_PROMPT, THREAT_SCORER_SYSTEM_PROMPT,
    SENTIMENT_ANALYSIS_PROMPT, PROACTIVE_FORECAST_PROMPT, LEGAL_REGULATORY_RISK_PROMPT,
    CYBER_OT_RISK_PROMPT, ENVIRONMENTAL_EPIDEMIC_RISK_PROMPT
)
from plan_utils import get_plan_limits, check_user_rss_quota, increment_user_rss_usage
from translation_utils import translate_snippet

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
if RAILWAY_ENV:
    logger.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    logger.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY not set! LLM features will be disabled.")

SUMMARY_CACHE_FILE = "summary_cache.json"
SUMMARY_CACHE_MAX_ENTRIES = 10000
SUMMARY_CACHE_EXPIRY_DAYS = 30

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

def summarize_with_security_focus(text):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": SECURITY_SUMMARIZE_PROMPT + "\n\n" + text}
    ]
    grok_summary = grok_chat(messages)
    if grok_summary:
        return grok_summary
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.3
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.info(f"[OpenAI fallback error] {e}")
    return "No summary available due to an error."

def load_summary_cache():
    Path(SUMMARY_CACHE_FILE).touch(exist_ok=True)
    try:
        with open(SUMMARY_CACHE_FILE, "r") as f:
            cache = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        cache = {}
    now = time.time()
    cutoff = now - SUMMARY_CACHE_EXPIRY_DAYS * 86400
    # PATCH: Only call .get on dicts, skip any str/invalid entry
    filtered = {k: v for k, v in cache.items() if isinstance(v, dict) and v.get("timestamp", now) >= cutoff}
    if len(filtered) > SUMMARY_CACHE_MAX_ENTRIES:
        sorted_items = sorted(filtered.items(), key=lambda item: item[1].get("timestamp", 0), reverse=True)
        filtered = dict(sorted_items[:SUMMARY_CACHE_MAX_ENTRIES])
    return filtered

def save_summary_cache(cache):
    with open(SUMMARY_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)

def summarize_with_security_focus_cached(summarize_fn):
    cache = load_summary_cache()
    def wrapper(text):
        key = sha256(text.encode("utf-8")).hexdigest()
        now = time.time()
        if key in cache and cache[key].get("timestamp", 0) >= now - SUMMARY_CACHE_EXPIRY_DAYS * 86400:
            return cache[key]["summary"]
        summary = summarize_fn(text)
        cache[key] = {"summary": summary, "timestamp": now}
        if len(cache) > SUMMARY_CACHE_MAX_ENTRIES:
            oldest = sorted(cache.items(), key=lambda item: item[1].get("timestamp", 0))[:len(cache)-SUMMARY_CACHE_MAX_ENTRIES]
            for k, _ in oldest:
                del cache[k]
        save_summary_cache(cache)
        return summary
    return wrapper

summarize_with_security_grok = summarize_with_security_focus_cached(summarize_with_security_focus)

THREAT_CATEGORIES = [
    "Terrorism", "Protest", "Crime", "Kidnapping", "Cyber",
    "Natural Disaster", "Political", "Infrastructure", "Health", "Unclassified"
]

def classify_threat_type(text):
    import json as pyjson
    messages = [
        {"role": "system", "content": "You are a threat classifier. Respond with a JSON as: {\"label\": ..., \"confidence\": ...}"},
        {"role": "user", "content": TYPE_PROMPT + "\n\n" + text}
    ]
    try:
        grok_label = grok_chat(messages, temperature=0)
        if grok_label:
            try:
                parsed = pyjson.loads(grok_label)
                label = parsed.get("label", "Unclassified")
                confidence = float(parsed.get("confidence", 0.85))
            except Exception:
                label = grok_label.strip()
                confidence = 0.88 if label in THREAT_CATEGORIES else 0.5
            if label not in THREAT_CATEGORIES:
                label = "Unclassified"
                confidence = 0.5
            return {"label": label, "confidence": confidence}
    except Exception as e:
        logger.error(f"[classify_threat_type][Grok error] {e}")

    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0
            )
            try:
                parsed = pyjson.loads(response.choices[0].message.content)
                label = parsed.get("label", "Unclassified")
                confidence = float(parsed.get("confidence", 0.85))
            except Exception:
                label = response.choices[0].message.content.strip()
                confidence = 0.85 if label in THREAT_CATEGORIES else 0.5
            if label not in THREAT_CATEGORIES:
                label = "Unclassified"
                confidence = 0.5
            return {"label": label, "confidence": confidence}
        except Exception as e:
            logger.error(f"[classify_threat_type][OpenAI error] {e}")

    return {"label": "Unclassified", "confidence": 0.5}

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

def parse_relevance_score(llm_response):
    import re
    match = re.search(r"([01](?:\.\d+)?)", llm_response)
    if match:
        score = float(match.group(1))
        if 0.0 <= score <= 1.0:
            return score
    llm_response = llm_response.strip().lower()
    if llm_response.startswith("yes"):
        return 1.0
    elif llm_response.startswith("no"):
        return 0.0
    return 0.5

def llm_relevance_score(alert, region=None, city=None):
    location = ""
    if city and region:
        location = f"{city}, {region}"
    elif city:
        location = city
    elif region:
        location = region
    else:
        return 0.0
    text = (alert.get("title", "") + " " + alert.get("summary", ""))
    prompt = (
        f"How relevant is this security alert to {location}? Respond ONLY with a relevance confidence score from 0 (not relevant) to 1 (highly relevant). If you must answer yes/no, say Yes=1, No=0.\n\n"
        f"Alert:\n{text}\n"
    )
    messages = [{"role": "user", "content": prompt}]
    llm_response = grok_chat(messages, temperature=0)
    if llm_response:
        return parse_relevance_score(llm_response)
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0
            )
            txt = response.choices[0].message.content.strip()
            return parse_relevance_score(txt)
        except Exception as e:
            logger.error(f"[LLM relevance fallback error] {e}")
    return 0.5

def filter_alerts_llm(alerts, region=None, city=None, threshold=0.7, max_workers=4):
    if len(alerts) > 40:
        logger.warning(f"LLM filtering {len(alerts)} alerts! Consider increasing pre-filter strictness.")
    from concurrent.futures import ThreadPoolExecutor
    args = [(alert, region, city) for alert in alerts]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        scores = list(executor.map(lambda ac: llm_relevance_score(*ac), args))
    filtered = []
    for i, score in enumerate(scores):
        if score >= threshold:
            filtered.append(alerts[i])
        else:
            logger.info(f"Filtered out alert {alerts[i].get('title','')} with relevance score {score:.2f}")
    return filtered

def map_severity(score):
    if score is None:
        return "Unknown"
    if score >= 0.75:
        return "High"
    if score >= 0.45:
        return "Medium"
    return "Low"

async def get_clean_alerts_async(
    region=None, topic=None, city=None, limit=20, summarize=False,
    llm_location_filter=True, user_email=None, session_id=None,
    use_telegram=False,
    write_to_db=False
):
    if not user_email or not session_id:
        raise Exception("user_email and session_id are required for plan quota enforcement.")
    plan_limits = get_plan_limits(user_email)
    ok, msg = check_user_rss_quota(user_email, session_id, plan_limits)
    if not ok:
        logger.error(f"Quota exceeded: {msg}")
        return []
    increment_user_rss_usage(user_email, session_id, plan_limits.get('plan'))
    alerts = []
    seen = set()
    region_str = str(region).strip() if region else None
    topic_str = str(topic).lower() if isinstance(topic, str) and topic else "all"
    city_str = str(city).strip() if city else None

    feeds = get_feed_for_location(region=region_str, city=city_str, topic=topic_str)
    if not feeds:
        logger.info("⚠️ No feeds found for the given location/topic.")
        return []

    results = await asyncio.gather(*(fetch_feed_async(url) for url in feeds))

    telegram_alerts = []
    if use_telegram:
        try:
            telegram_alerts = scrape_telegram_messages(region=region_str, city=city_str, topic=topic_str, limit=limit)
            logger.info(f"Loaded {len(telegram_alerts)} alerts from Telegram OSINT.")
        except Exception as e:
            logger.warning(f"Telegram scraping failed: {e}")

    for feed, source_url in results:
        if not feed or 'entries' not in feed:
            continue

        source_domain = urlparse(source_url).netloc.replace("www.", "")
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()
            subtitle = first_sentence(summary)
            search_text = f"{title}. {subtitle}".lower()
            link = entry.get("link", "").strip()
            published = entry.get("published", "")

            lang = safe_detect_lang(search_text)
            threat_match = any_multilingual_keyword(search_text, lang, TRANSLATED_KEYWORDS)
            english_match = KEYWORD_PATTERN.search(search_text)
            if not (threat_match or english_match):
                continue

            snippet = f"{title}. {summary}".strip()
            if lang != "en":
                en_snippet = translate_snippet(snippet, lang)
            else:
                en_snippet = snippet

            dedupe_key = sha256(f"{title}:{subtitle}".encode("utf-8")).hexdigest()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            keyword_weight = compute_keyword_weight(snippet)

            alert = {
                "uuid": dedupe_key,
                "title": title,
                "summary": summary,
                "en_snippet": en_snippet,
                "gpt_summary": "",
                "link": link,
                "source": source_domain,
                "published": published,
                "region": region_str,
                "country": None,
                "city": city_str,
                "type": "",
                "type_confidence": None,
                "threat_level": "",
                "level": "",
                "threat_label": "",
                "score": None,
                "confidence": None,
                "reasoning": "",
                "review_flag": False,
                "review_notes": "",
                "ingested_at": datetime.utcnow(),
                "timestamp": datetime.utcnow().isoformat(),
                "model_used": "",
                "sentiment": "",
                "forecast": "",
                "legal_risk": "",
                "cyber_ot_risk": "",
                "environmental_epidemic_risk": "",
                "keyword_weight": keyword_weight,
                "tags": [],
            }

            try:
                alert_text = f"{title}: {summary}"
                threat_result = assess_threat_level(
                    alert_text=alert_text,
                    triggers=[],
                    location=city or region or "",
                    alert_uuid=dedupe_key,
                    plan="FREE",
                    enrich=True
                )
                alert["threat_label"] = threat_result.get("threat_label", threat_result.get("label", "Unrated"))
                alert["score"] = min(100, max(0, (threat_result.get("score", 0) or 0) + keyword_weight))
                alert["confidence"] = threat_result.get("confidence", 0.0)
                alert["reasoning"] = threat_result.get("reasoning", "")
                alert["review_flag"] = threat_result.get("review_flag", False)
                alert["level"] = alert.get("threat_label", "Unknown")
                alert["sentiment"] = threat_result.get("sentiment", "")
                alert["forecast"] = threat_result.get("forecast", "")
                alert["legal_risk"] = threat_result.get("legal_risk", "")
                alert["cyber_ot_risk"] = threat_result.get("cyber_ot_risk", "")
                alert["environmental_epidemic_risk"] = threat_result.get("environmental_epidemic_risk", "")
                alert["threat_level"] = alert["threat_label"]
                enrich_log(alert)
            except Exception as e:
                logger.error(f"[RSS_PROCESSOR_ERROR][THREAT_SCORER] {e} | Alert: {title}")
                alert["threat_label"] = "Unrated"
                alert["score"] = 0
                alert["reasoning"] = f"Threat scorer failed: {e}"
                alert["confidence"] = 0.0
                alert["review_flag"] = True
                alert["review_notes"] = "Could not auto-score threat; requires analyst review."
                alert["timestamp"] = datetime.utcnow().isoformat()
                alert["level"] = "Unknown"
                alert["threat_level"] = "Unknown"

            try:
                threat_type = classify_threat_type(summary)
                alert["type"] = threat_type["label"]
                alert["type_confidence"] = threat_type["confidence"]
            except Exception as e:
                logger.error(f"[RSS_PROCESSOR_ERROR][ThreatType] {e} | Alert: {title}")
                alert["type"] = "Unclassified"
                alert["type_confidence"] = 0.5

            alerts.append(alert)
            if len(alerts) >= limit:
                logger.info(f"✅ Parsed {len(alerts)} alerts.")
                break
        if len(alerts) >= limit:
            break

    if use_telegram:
        for telegram_alert in telegram_alerts:
            dedupe_key = sha256((telegram_alert.get("title", "") + ":" + telegram_alert.get("summary", "")).encode("utf-8")).hexdigest()
            if dedupe_key in seen:
                continue
            telegram_alert['uuid'] = dedupe_key
            telegram_alert['source'] = "telegram"
            telegram_alert['keyword_weight'] = compute_keyword_weight(telegram_alert.get("title", "") + " " + telegram_alert.get("summary", ""))
            telegram_alert['ingested_at'] = datetime.utcnow()
            telegram_alert['tags'] = []
            alerts.append(telegram_alert)
            seen.add(dedupe_key)

    if llm_location_filter and (city_str or region_str):
        logger.info("🔍 Running LLM-based location relevance filtering...")
        alerts = filter_alerts_llm(alerts, region=region_str, city=city_str)
    if not alerts:
        logger.error("⚠️ No relevant alerts found for city/region. Will use fallback advisory.")
        return []

    logger.info(f"✅ Parsed {len(alerts)} location-relevant alerts.")

    if write_to_db:
        try:
            logger.info(f"Writing {len(alerts)} alerts to DB...")
            save_alerts_to_db(alerts)
            logger.info("Alerts saved to DB successfully.")
        except Exception as e:
            logger.error(f"Failed to save alerts to DB: {e}")

    return alerts[:limit]

def get_clean_alerts_cached(get_clean_alerts_fn_async):
    def wrapper(*args, **kwargs):
        summarize = kwargs.get("summarize", False)
        region = kwargs.get("region", None)
        city = kwargs.get("city", None)
        topic = kwargs.get("topic", None)
        user_email = kwargs.get("user_email", None)
        use_telegram = kwargs.get("use_telegram", False)
        write_to_db = kwargs.get("write_to_db", False)

        if summarize or region or city or topic or use_telegram or write_to_db:
            return asyncio.run(get_clean_alerts_fn_async(*args, **kwargs))

        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        cache_dir = "cache"
        Path(cache_dir).mkdir(exist_ok=True)
        cache_path = os.path.join(cache_dir, f"alerts-{today_str}.json")

        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                logger.info(f"[CACHE] Loaded alerts from cache: {cache_path}")
                return json.load(f)

        alerts = asyncio.run(get_clean_alerts_fn_async(*args, **kwargs))
        with open(cache_path, "w") as f:
            json.dump(alerts, f, indent=2)
        logger.info(f"✅ Saved {len(alerts)} alerts to cache: {cache_path}")
        return alerts

    return wrapper

def generate_fallback_summary(region, threat_type, city=None):
    location = f"{city}, {region}" if city and region else (city or region or "your location")
    prompt = FALLBACK_PROMPT.format(location=location, threat_type=threat_type)
    messages = [{"role": "user", "content": prompt}]
    grok_summary = grok_chat(messages, temperature=0.4)
    if grok_summary:
        return grok_summary
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.4
            )
            return response.choices[0].message.content.strip()
        except Exception as e2:
            return f"⚠️ Fallback error: {str(e2)}"
    return f"⚠️ Fallback error: Could not generate summary."

get_clean_alerts = get_clean_alerts_cached(get_clean_alerts_async)

if __name__ == "__main__":
    logger.info("🔍 Running standalone RSS processor...")
    test_email = "zika.rakita@gmail.com"
    alerts = get_clean_alerts(region="Afghanistan", limit=5, summarize=True, user_email=test_email, session_id="demo", use_telegram=False, write_to_db=True)
    if not alerts:
        logger.info("No relevant alerts found. Generating fallback advisory...")
        logger.info(generate_fallback_summary(region="Afghanistan", threat_type="All"))
    else:
        logger.info(f"Alerts processed: {len(alerts)}")
        for alert in alerts:
            logger.info(json.dumps(alert, indent=2))