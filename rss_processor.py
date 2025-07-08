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

# Import feed catalogs from external file
from feeds_catalog import LOCAL_FEEDS, COUNTRY_FEEDS, GLOBAL_FEEDS

load_dotenv()  # Load environment variables

from telegram_scraper import scrape_telegram_messages
from xai_client import grok_chat
from openai import OpenAI

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

system_prompt = """
You are Sentinel AI — an intelligent threat analyst created by Zika Rakita, founder of Zika Risk.
You deliver concise, professional threat summaries and actionable advice. Speak with clarity and authority.
If the user is not a subscriber, end with:
“To receive personalized alerts, intelligence briefings, and emergency support, upgrade your access at zikarisk.com.”
"""

SUMMARY_LIMIT = 5

def get_feeds_for_location(region=None, city=None):
    """Return the most specific feed(s) for the query."""
    city_key = city.lower().strip() if city else None
    region_key = region.lower().strip() if region else None
    if city_key and city_key in LOCAL_FEEDS:
        return LOCAL_FEEDS[city_key]
    if region_key and region_key in COUNTRY_FEEDS:
        return COUNTRY_FEEDS[region_key]
    return GLOBAL_FEEDS

def summarize_with_fallback(text):
    messages = [
        {"role": "system", "content": system_prompt},
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
                temperature=0.3,
                max_tokens=300
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

TYPE_PROMPT = """
Classify the threat type based on the following news headline and summary. Choose only ONE of the following categories:
- Terrorism
- Protest
- Crime
- Kidnapping
- Cyber
- Natural Disaster
- Political
- Infrastructure
- Health
- Unclassified
Respond with only the category name.
"""

THREAT_CATEGORIES = [
    "Terrorism", "Protest", "Crime", "Kidnapping", "Cyber",
    "Natural Disaster", "Political", "Infrastructure", "Health", "Unclassified"
]

def classify_threat_type(text):
    messages = [
        {"role": "system", "content": "You are a threat classifier. Respond only with one category."},
        {"role": "user", "content": TYPE_PROMPT + "\n\n" + text}
    ]
    grok_label = grok_chat(messages, max_tokens=10, temperature=0)
    if grok_label and grok_label in THREAT_CATEGORIES:
        return grok_label
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0,
                max_tokens=10
            )
            label = response.choices[0].message.content.strip()
            if label not in THREAT_CATEGORIES:
                return "Unclassified"
            return label
        except Exception as e:
            print(f"[OpenAI fallback error] {e}")
    return "Unclassified"

def fetch_feed(url, timeout=7, retries=3, backoff=1.5):
    attempt = 0
    while attempt < retries:
        try:
            response = httpx.get(url, timeout=timeout)
            if response.status_code == 200:
                print(f"✅ Fetched: {url}")
                return feedparser.parse(response.content.decode('utf-8', errors='ignore')), url
            else:
                print(f"⚠️ Feed returned {response.status_code}: {url}")
        except Exception as e:
            print(f"❌ Attempt {attempt + 1} failed for {url} — {e}")
        attempt += 1
        time.sleep(backoff ** attempt)
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
    answer = grok_chat(messages, max_tokens=3, temperature=0)
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
                temperature=0,
                max_tokens=3
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

def get_clean_alerts(region=None, topic=None, city=None, limit=20, summarize=False, llm_location_filter=True):
    alerts = []
    seen = set()
    region_str = str(region).strip() if region else None
    topic_str = str(topic).lower() if isinstance(topic, str) and topic else "all"
    city_str = str(city).strip() if city else None

    feeds = get_feeds_for_location(region=region_str, city=city_str)

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
            full_text = f"{title}: {summary}".lower()

            if topic_str != "all" and topic_str not in full_text:
                continue
            if not KEYWORD_PATTERN.search(full_text):
                continue

            key = f"{title}:{summary}"
            if key in seen:
                continue
            seen.add(key)

            alerts.append({
                "title": title,
                "summary": summary,
                "link": link,
                "source": source_domain
            })

            if len(alerts) >= limit:
                print(f"✅ Parsed {len(alerts)} alerts.")
                break
        if len(alerts) >= limit:
            break

    # LLM Location Filtering
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
        with ThreadPoolExecutor(max_workers=5) as executor:
            threat_types = list(executor.map(lambda alert: classify_threat_type(alert["summary"]), filtered_alerts))
        for i, alert in enumerate(filtered_alerts):
            alert["type"] = threat_types[i]
        filtered_alerts = parallel_summarize_alerts(filtered_alerts, summarize_with_grok)
    else:
        for alert in filtered_alerts:
            alert["type"] = classify_threat_type(alert["summary"])

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
    prompt = f"""
You are Sentinel AI, an elite threat analyst created by Zika Rakita at Zika Risk.

No current threat alerts were found for:
- Location: {location}
- Threat Type: {threat_type}

Based on global intelligence patterns, provide a realistic and professional advisory summary (150–250 words) for travelers or security professionals. Mention relevant threats, operational considerations, and situational awareness — even if generalized. This should sound like real field intelligence, not generic advice.

Respond in professional English. Output in plain text.
"""
    messages = [{"role": "user", "content": prompt}]
    grok_summary = grok_chat(messages, max_tokens=300, temperature=0.4)
    if grok_summary:
        return grok_summary
    if openai_client:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                temperature=0.4,
                max_tokens=300
            )
            return response.choices[0].message.content.strip()
        except Exception as e2:
            return f"⚠️ Fallback error: {str(e2)}"
    return f"⚠️ Fallback error: Could not generate summary."

summarize_with_grok = summarize_with_grok_cached(summarize_with_fallback)
get_clean_alerts = get_clean_alerts_cached(get_clean_alerts)

if __name__ == "__main__":
    print("🔍 Running standalone RSS processor...")
    # Example: get_clean_alerts(region="uk", city="london", limit=5, summarize=True)
    alerts = get_clean_alerts(region="uk", city="london", limit=5, summarize=True)
    if not alerts:
        print("No relevant alerts found. Generating fallback advisory...")
        print(generate_fallback_summary(region="uk", threat_type="All", city="london"))
    else:
        for alert in alerts:
            print(json.dumps(alert, indent=2))