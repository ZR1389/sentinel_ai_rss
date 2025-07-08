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

from telegram_scraper import scrape_telegram_messages

# --- Mistral AI (new client import) ---
from mistralai import MistralClient, ChatMessage

load_dotenv()
client = MistralClient(api_key=os.getenv("MISTRAL_API_KEY"))

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

FEEDS = [
    "https://www.cisa.gov/news.xml",
    "https://feeds.bbci.co.uk/news/uk/rss.xml",
    "https://www.darkreading.com/rss.xml",
    "https://krebsonsecurity.com/feed/",
    "https://www.bleepingcomputer.com/feed/",
    "https://www.theguardian.com/world/rss",
    "https://news.un.org/feed/subscribe/en/news/all/rss.xml",
    "https://www.crimemagazine.com/rss.xml",
    "https://www.murdermap.co.uk/feed/",
    "https://kidnappingmurderandmayhem.blogspot.com/feeds/posts/default",
    "https://www.securitymagazine.com/rss/",
    "https://feeds.feedburner.com/TheHackersNews",
    "https://www.csoonline.com/feed/",
    "https://www.arlingtoncardinal.com/category/crime/feed/",
    "https://intel471.com/blog/feed",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://www.france24.com/en/rss",
    "https://www.gov.uk/foreign-travel-advice.atom",
]

MISTRAL_SUMMARY_MODEL = os.getenv("MISTRAL_SUMMARY_MODEL", "mistral-small-3.2")
MISTRAL_CLASSIFY_MODEL = os.getenv("MISTRAL_CLASSIFY_MODEL", "mistral-small-3.2")

system_prompt = """
You are Sentinel AI — an intelligent threat analyst created by Zika Rakita, founder of Zika Risk.
You deliver concise, professional threat summaries and actionable advice. Speak with clarity and authority.
If the user is not a subscriber, end with:
“To receive personalized alerts, intelligence briefings, and emergency support, upgrade your access at zikarisk.com.”
"""

SUMMARY_LIMIT = 5

def summarize_with_mistral(text):
    try:
        response = client.chat(
            model=MISTRAL_SUMMARY_MODEL,
            messages=[
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=f"Summarize this for a traveler:\n\n{text}")
            ],
            temperature=0.3,
            max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[Mistral error] {str(e)}")
        return "No summary available due to an error."

def summarize_with_mistral_cached(summarize_fn):
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

def classify_threat_type(text):
    try:
        response = client.chat(
            model=MISTRAL_CLASSIFY_MODEL,
            messages=[
                ChatMessage(role="system", content="You are a threat classifier. Respond only with one category."),
                ChatMessage(role="user", content=TYPE_PROMPT + "\n\n" + text)
            ],
            temperature=0,
            max_tokens=10
        )
        label = response.choices[0].message.content.strip()
        if label not in [
            "Terrorism", "Protest", "Crime", "Kidnapping", "Cyber",
            "Natural Disaster", "Political", "Infrastructure", "Health", "Unclassified"
        ]:
            return "Unclassified"
        return label
    except Exception as e:
        print(f"❌ Threat type classification error: {e}")
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

def get_clean_alerts(region=None, topic=None, limit=20, summarize=False):
    alerts = []
    seen = set()

    region_str = str(region).lower() if isinstance(region, str) else "all"
    topic_str = str(topic).lower() if isinstance(topic, str) else "all"

    try:
        telegram_alerts = scrape_telegram_messages()
        if telegram_alerts and isinstance(telegram_alerts, list):
            for tg in telegram_alerts:
                full_text = f"{tg['title']} {tg['summary']}".lower()
                if region_str != "all" and region_str not in full_text:
                    continue
                if topic_str != "all" and topic_str not in full_text:
                    continue

                alerts.append({
                    "title": tg["title"],
                    "summary": tg["summary"],
                    "link": tg["link"],
                    "source": tg["source"]
                })

                if len(alerts) >= limit:
                    print(f"✅ Parsed {len(alerts)} alerts.")
                    break
    except Exception as e:
        print(f"❌ Telegram scrape failed: {e}")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(fetch_feed, FEEDS))

    for feed, source_url in results:
        if not feed or 'entries' not in feed:
            continue

        source_domain = urlparse(source_url).netloc.replace("www.", "")
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()
            link = entry.get("link", "").strip()
            full_text = f"{title}: {summary}".lower()

            if region_str != "all" and region_str not in full_text:
                continue
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

    if summarize and alerts:
        with ThreadPoolExecutor(max_workers=5) as executor:
            threat_types = list(executor.map(lambda alert: classify_threat_type(alert["summary"]), alerts))
        for i, alert in enumerate(alerts):
            alert["type"] = threat_types[i]
        alerts = parallel_summarize_alerts(alerts, summarize_with_mistral)
    else:
        for alert in alerts:
            alert["type"] = classify_threat_type(alert["summary"])

    print(f"✅ Parsed {len(alerts)} alerts.")
    return alerts[:limit]

def get_clean_alerts_cached(get_clean_alerts_fn):
    def wrapper(*args, **kwargs):
        summarize = kwargs.get("summarize", False)
        region = kwargs.get("region", None)
        topic = kwargs.get("topic", None)

        if summarize or region or topic:
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

def generate_fallback_summary(region, threat_type):
    prompt = f"""
You are Sentinel AI, an elite threat analyst created by Zika Rakita at Zika Risk.

No current threat alerts were found for:
- Region: {region}
- Threat Type: {threat_type}

Based on global intelligence patterns, provide a realistic and professional advisory summary (150–250 words) for travelers or security professionals. Mention relevant threats, operational considerations, and situational awareness — even if generalized. This should sound like real field intelligence, not generic advice.

Respond in professional English. Output in plain text.
"""
    try:
        response = client.chat(
            model=MISTRAL_SUMMARY_MODEL,
            messages=[ChatMessage(role="user", content=prompt)],
            temperature=0.4
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"⚠️ Fallback error: {str(e)}"

summarize_with_mistral = summarize_with_mistral_cached(summarize_with_mistral)
get_clean_alerts = get_clean_alerts_cached(get_clean_alerts)

if __name__ == "__main__":
    print("🔍 Running standalone RSS processor...")
    alerts = get_clean_alerts()
    print(f"✅ Parsed {len(alerts)} alerts.")