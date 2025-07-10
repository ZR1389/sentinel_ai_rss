import os
import re
import time
import json
import httpx
import feedparser
from datetime import datetime
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from hashlib import sha256
from pathlib import Path
from unidecode import unidecode
import difflib

from feeds_catalog import LOCAL_FEEDS, COUNTRY_FEEDS, GLOBAL_FEEDS

with open('fcdo_country_feeds.json', 'r', encoding='utf-8') as f:
    FCDO_FEEDS = json.load(f)

load_dotenv()

from telegram_scraper import scrape_telegram_messages
from xai_client import grok_chat
from openai import OpenAI
from threat_scorer import assess_threat_level
from prompts import SYSTEM_PROMPT, TYPE_PROMPT, FALLBACK_PROMPT

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

THREAT_KEYWORDS = [
    "assassination", "mass shooting", "hijacking", "kidnapping", "bombing",
    "improvised explosive device", "IED", "gunfire", "active shooter", "terrorist attack",
    "suicide bombing", "military raid", "abduction", "hostage situation",
    "civil unrest", "riot", "protest", "coup d'etat", "regime change",
    "political unrest", "uprising", "insurrection", "state of emergency", "martial law",
    "evacuation", "roadblock", "border closure", "curfew", "flight cancellation",
    "airport closure", "port closure", "embassy alert", "travel advisory", "travel ban",
    "pandemic", "viral outbreak", "disease spread", "contamination", "quarantine",
    "public health emergency", "infectious disease", "epidemic", "biological threat", "health alert",
    "data breach", "ransomware", "cyberattack", "hacktivism", "deepfake", "phishing",
    "malware", "cyber espionage", "identity theft", "network security",
    "extremist activity", "radicalization", "border security", "smuggling", "human trafficking",
    "natural disaster", "earthquake", "tsunami", "tornado", "hurricane", "flood", "wild fire",
    "lockdown", "security alert", "critical infrastructure"
]

KEYWORD_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in THREAT_KEYWORDS) + r')\b',
    re.IGNORECASE
)

SUMMARY_LIMIT = 5

# --- City normalization and fuzzy matching logic ---

# Normalize LOCAL_FEEDS at load time
NORMALIZED_LOCAL_FEEDS = {unidecode(city).lower().strip(): v for city, v in LOCAL_FEEDS.items()}

def get_feed_for_city(city):
    if not city:
        return None
    city_key = unidecode(city).lower().strip()
    # Fuzzy match with a reasonable cutoff for typos/variants
    match = difflib.get_close_matches(city_key, NORMALIZED_LOCAL_FEEDS.keys(), n=1, cutoff=0.8)
    if match:
        return NORMALIZED_LOCAL_FEEDS[match[0]]
    return None

def get_feed_for_location(region=None, city=None, topic=None):
    region_key = region.strip().title() if region else None
    if region_key and region_key in FCDO_FEEDS:
        return [FCDO_FEEDS[region_key]]
    # Use improved city matching here!
    city_feeds = get_feed_for_city(city)
    if city_feeds:
        return city_feeds
    if topic and topic.lower() == "cyber":
        try:
            from feeds_catalog import CYBER_FEEDS
            return CYBER_FEEDS
        except ImportError:
            pass
    region_key_lower = region.lower().strip() if region else None
    if region_key_lower and region_key_lower in COUNTRY_FEEDS:
        return COUNTRY_FEEDS[region_key_lower]
    return GLOBAL_FEEDS

def summarize_with_fallback(text):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Summarize this for a traveler:\n\n{text}"}
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
            print(f"[OpenAI fallback error] {e}")
    return "No summary available due to an error."

def summarize_with_grok_cached(summarize_fn):
    cache_file = "summary_cache.json"
    Path(cache_file).touch(exist_ok=True)
    try:
        with open(cache_file, "r") as f:
            cache = json.load(f)
    except json.JSONDecodeError:
        cache = {}

    def wrapper(text):
        key = sha256(text.encode("utf-8")).hexdigest()
        if key in cache:
            return cache[key]
        summary = summarize_fn(text)
        cache[key] = summary
        with open(cache_file, "w") as f:
            json.dump(cache, f, indent=2)
        return summary

    return wrapper

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
        print(f"[classify_threat_type][Grok error] {e}")

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
            print(f"[classify_threat_type][OpenAI error] {e}")

    return {"label": "Unclassified", "confidence": 0.5}

def fetch_feed(url, timeout=7, retries=3, backoff=1.5, max_backoff=60):
    attempt = 0
    current_backoff = backoff
    while attempt < retries:
        try:
            response = httpx.get(url, timeout=timeout)
            if response.status_code == 200:
                print(f"✅ Fetched: {url}")
                return feedparser.parse(response.content.decode('utf-8', errors='ignore')), url
            elif response.status_code in [429, 503]:
                current_backoff = min(current_backoff * 2, max_backoff)
                print(f"⚠️ Throttled ({response.status_code}) by {url}; backing off for {current_backoff} seconds")
                time.sleep(current_backoff)
            else:
                print(f"⚠️ Feed returned {response.status_code}: {url}")
        except Exception as e:
            print(f"❌ Attempt {attempt + 1} failed for {url} — {e}")
        attempt += 1
        time.sleep(current_backoff)
    print(f"❌ Failed to fetch after {retries} retries: {url}")
    return None, url

def parallel_summarize_alerts(alerts, summarize_fn, limit=SUMMARY_LIMIT, max_workers=5):
    to_summarize = alerts[:limit]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        summaries = list(executor.map(lambda alert: summarize_fn(alert["summary"]), to_summarize))
    for i, alert in enumerate(to_summarize):
        alert["gpt_summary"] = summaries[i]
    for alert in alerts[limit:]:
        alert["gpt_summary"] = f"Summary not generated (limit {limit} reached)"
    return alerts

def llm_is_alert_relevant(alert, region=None, city=None):
    location = ""
    if city and region:
        location = f"{city}, {region}"
    elif city:
        location = city
    elif region:
        location = region
    else:
        return False

    text = (alert.get("title", "") + " " + alert.get("summary", ""))
    prompt = (
        f"Is the following security alert directly relevant to {location}? "
        "Be strict: Only answer Yes if the alert concerns events happening in, targeting, or otherwise mentioning this location. "
        "If it's general, about another country/region, or does not mention this location, answer No.\n\n"
        f"Alert:\n{text}\n\n"
        "Reply with only Yes or No."
    )
    messages = [{"role": "user", "content": prompt}]
    answer = grok_chat(messages, temperature=0)
    if answer:
        answer = answer.strip().lower()
        if answer.startswith("yes"):
            return True
        if answer.startswith("no"):
            return False
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0
            )
            txt = response.choices[0].message.content.strip().lower()
            if txt.startswith("yes"):
                return True
            if txt.startswith("no"):
                return False
        except Exception as e:
            print(f"[LLM relevance fallback error] {e}")
    return False

def filter_alerts_llm(alerts, region=None, city=None, max_workers=4):
    args = [(alert, region, city) for alert in alerts]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        relevant_flags = list(executor.map(lambda ac: llm_is_alert_relevant(*ac), args))
    filtered = []
    for i, flag in enumerate(relevant_flags):
        if flag:
            filtered.append(alerts[i])
    return filtered

def map_severity(score):
    if score is None:
        return "Unknown"
    if score >= 0.75:
        return "High"
    if score >= 0.45:
        return "Medium"
    return "Low"

def get_clean_alerts(region=None, topic=None, city=None, limit=20, summarize=False, llm_location_filter=True):
    alerts = []
    seen = set()
    region_str = str(region).strip() if region else None
    topic_str = str(topic).lower() if isinstance(topic, str) and topic else "all"
    city_str = str(city).strip() if city else None

    feeds = get_feed_for_location(region=region_str, city=city_str, topic=topic_str)
    if not feeds:
        print("⚠️ No feeds found for the given location/topic.")
        return []

    with ThreadPoolExecutor(max_workers=len(feeds)) as executor:
        results = list(executor.map(fetch_feed, feeds))

    for feed, source_url in results:
        if not feed or 'entries' not in feed:
            continue

        source_domain = urlparse(source_url).netloc.replace("www.", "")
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()
            link = entry.get("link", "").strip()
            published = entry.get("published", "")
            full_text = f"{title}: {summary}".lower()

            if topic_str != "all" and topic_str not in full_text:
                continue
            if not KEYWORD_PATTERN.search(full_text):
                continue

            dedupe_key = sha256(f"{title}:{summary}".encode("utf-8")).hexdigest()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            alert = {
                "uuid": dedupe_key,
                "title": title,
                "summary": summary,
                "gpt_summary": "",
                "link": link,
                "source": source_domain,
                "published": published,
                "region": region_str,
                "city": city_str,
                "type": "",
                "type_confidence": None,
                "severity": "",
                "threat_label": "",
                "score": None,
                "confidence": None,
                "reasoning": "",
                "review_flag": False,
                "review_notes": "",
                "timestamp": datetime.utcnow().isoformat(),
                "model_used": "",
            }
            try:
                alert_text = f"{title}: {summary}"
                threat_result = assess_threat_level(
                    alert_text=alert_text,
                    triggers=[],  # Could parse triggers from summary/title if needed
                    location=city or region or "",
                    alert_uuid=dedupe_key
                )
                for k, v in threat_result.items():
                    alert[k] = v
                alert["severity"] = map_severity(alert.get("score"))
                alert["model_used"] = threat_result.get("model_used", "")
            except Exception as e:
                print(f"[RSS_PROCESSOR_ERROR][THREAT_SCORER] {e} | Alert: {title}")
                alert["threat_label"] = "Unrated"
                alert["score"] = 0
                alert["reasoning"] = f"Threat scorer failed: {e}"
                alert["confidence"] = 0.0
                alert["review_flag"] = True
                alert["review_notes"] = "Could not auto-score threat; requires analyst review."
                alert["timestamp"] = datetime.utcnow().isoformat()
                alert["severity"] = "Unknown"

            try:
                threat_type = classify_threat_type(summary)
                alert["type"] = threat_type["label"]
                alert["type_confidence"] = threat_type["confidence"]
            except Exception as e:
                print(f"[RSS_PROCESSOR_ERROR][ThreatType] {e} | Alert: {title}")
                alert["type"] = "Unclassified"
                alert["type_confidence"] = 0.5

            alerts.append(alert)

            if len(alerts) >= limit:
                print(f"✅ Parsed {len(alerts)} alerts.")
                break
        if len(alerts) >= limit:
            break

    filtered_alerts = []
    if llm_location_filter and (city_str or region_str):
        print("🔍 Running LLM-based location relevance filtering...")
        filtered_alerts = filter_alerts_llm(alerts, region=region_str, city=city_str)
    else:
        filtered_alerts = alerts

    if not filtered_alerts:
        print("⚠️ No relevant alerts found for city/region. Will use fallback advisory.")
        return []

    if summarize and filtered_alerts:
        filtered_alerts = parallel_summarize_alerts(filtered_alerts, summarize_with_grok)
    else:
        for alert in filtered_alerts:
            alert.setdefault("gpt_summary", "")

    print(f"✅ Parsed {len(filtered_alerts)} location-relevant alerts.")
    return filtered_alerts[:limit]

def get_clean_alerts_cached(get_clean_alerts_fn):
    def wrapper(*args, **kwargs):
        summarize = kwargs.get("summarize", False)
        region = kwargs.get("region", None)
        city = kwargs.get("city", None)
        topic = kwargs.get("topic", None)

        if summarize or region or city or topic:
            return get_clean_alerts_fn(*args, **kwargs)

        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        cache_dir = "cache"
        Path(cache_dir).mkdir(exist_ok=True)
        cache_path = os.path.join(cache_dir, f"alerts-{today_str}.json")

        if os.path.exists(cache_path):
            with open(cache_path, "r") as f:
                print(f"[CACHE] Loaded alerts from cache: {cache_path}")
                return json.load(f)

        alerts = get_clean_alerts_fn(*args, **kwargs)
        with open(cache_path, "w") as f:
            json.dump(alerts, f, indent=2)
        print(f"✅ Saved {len(alerts)} alerts to cache: {cache_path}")
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

summarize_with_grok = summarize_with_grok_cached(summarize_with_fallback)
get_clean_alerts = get_clean_alerts_cached(get_clean_alerts)

if __name__ == "__main__":
    print("🔍 Running standalone RSS processor...")
    alerts = get_clean_alerts(region="Afghanistan", limit=5, summarize=True)
    if not alerts:
        print("No relevant alerts found. Generating fallback advisory...")
        print(generate_fallback_summary(region="Afghanistan", threat_type="All"))
    else:
        for alert in alerts:
            print(json.dumps(alert, indent=2))