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
from openai import OpenAI
from hashlib import sha256
from pathlib import Path

from telegram_scraper import scrape_telegram_messages  # NEW

# -------------------------------
# 🚨 THREAT KEYWORDS (intelligence-grade)
# -------------------------------
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

# -------------------------------
# ALL RSS FEEDS
# -------------------------------
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
    "https://www.gdacs.org/xml/rss.xml",

]

# -------------------------------
# GPT SETUP
# -------------------------------
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
GPT_SUMMARY_MODEL = os.getenv("GPT_SUMMARY_MODEL", "gpt-4o")
GPT_CLASSIFY_MODEL = os.getenv("GPT_CLASSIFY_MODEL", "gpt-4o")

system_prompt = """
You are Sentinel AI — an intelligent threat analyst created by Zika Rakita, founder of Zika Risk.
You deliver concise, professional threat summaries and actionable advice. Speak with clarity and authority.
If the user is not a subscriber, end with:
“To receive personalized alerts, intelligence briefings, and emergency support, upgrade your access at zikarisk.com.”
"""

def summarize_with_gpt(text):
    try:
        response = client.chat.completions.create(
            model=GPT_SUMMARY_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Summarize this for a traveler:\n\n{text}"}
            ],
            temperature=0.3,
            max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[GPT error] {str(e)}"

def summarize_with_gpt_cached(summarize_fn):
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
Example:
Input: "Hacking group hits hospital IT system"
Output: Cyber
Now classify this:
"""

def classify_threat_type(text):
    try:
        response = client.chat.completions.create(
            model=GPT_CLASSIFY_MODEL,
            messages=[
                {"role": "system", "content": "You are a threat classifier. Respond only with one category."},
                {"role": "user", "content": TYPE_PROMPT + "\n\n" + text}
            ],
            temperature=0,
            max_tokens=10
        )
        label = response.choices[0].message.content.strip()
        if label not in ["Terrorism", "Protest", "Crime", "Kidnapping", "Cyber",
                         "Natural Disaster", "Political", "Infrastructure", "Health", "Unclassified"]:
            return "Unclassified"
        return label
    except Exception as e:
        print(f"\u274c Threat type classification error: {e}")
        return "Unclassified"

def fetch_feed(url, timeout=7, retries=3, backoff=1.5):
    attempt = 0
    while attempt < retries:
        try:
            response = httpx.get(url, timeout=timeout)
            if response.status_code == 200:
                print(f"\u2705 Fetched: {url}")
                return feedparser.parse(response.content.decode('utf-8', errors='ignore')), url
            else:
                print(f"\u26a0\ufe0f Feed returned {response.status_code}: {url}")
        except Exception as e:
            print(f"\u274c Attempt {attempt + 1} failed for {url} — {e}")
        attempt += 1
        time.sleep(backoff ** attempt)
    print(f"\u274c Failed to fetch after {retries} retries: {url}")
    return None, url

def get_clean_alerts(region=None, topic=None, limit=20, summarize=False):
    alerts = []
    seen = set()

    try:
        telegram_alerts = scrape_telegram_messages()
        for tg in telegram_alerts:
            if region and region.lower() not in tg["summary"].lower():
                continue
            if topic and topic.lower() not in tg["summary"].lower():
                continue

            gpt_summary = summarize_with_gpt(tg["summary"]) if summarize else None
            threat_type = classify_threat_type(tg["summary"])

            alerts.append({
                "title": tg["title"],
                "summary": tg["summary"],
                "link": tg["link"],
                "source": tg["source"],
                "gpt_summary": gpt_summary,
                "type": threat_type
            })

            if len(alerts) >= limit:
                print(f"\u2705 Parsed {len(alerts)} alerts.")
                return alerts
    except Exception as e:
        print(f"\u274c Telegram scrape failed: {e}")

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
            full_text = f"{title}: {summary}"

            if region and region.lower() not in full_text.lower():
                continue
            if topic and topic.lower() not in full_text.lower():
                continue
            if not KEYWORD_PATTERN.search(full_text):
                continue

            key = f"{title}:{summary}"
            if key in seen:
                continue
            seen.add(key)

            gpt_summary = summarize_with_gpt(full_text) if summarize else None
            threat_type = classify_threat_type(full_text)

            alerts.append({
                "title": title,
                "summary": summary,
                "link": link,
                "source": source_domain,
                "gpt_summary": gpt_summary,
                "type": threat_type
            })

            if len(alerts) >= limit:
                print(f"\u2705 Parsed {len(alerts)} alerts.")
                return alerts

    print(f"\u2705 Parsed {len(alerts)} alerts.")
    # ✅ Filter alerts by region and topic
    if region or topic:
        filtered = []
        for alert in alerts:
            if region and alert.get("region", "").strip() != region:
                continue
            if topic and alert.get("type", "").strip() != topic:
                continue
            filtered.append(alert)
        return filtered[:limit]
    
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
        print(f"\u2705 Saved {len(alerts)} alerts to cache: {cache_path}")
        return alerts

    return wrapper

# Apply wrappers
summarize_with_gpt = summarize_with_gpt_cached(summarize_with_gpt)
get_clean_alerts = get_clean_alerts_cached(get_clean_alerts)

if __name__ == "__main__":
    print("🔍 Running standalone RSS processor...")
    alerts = get_clean_alerts()
    print(f"✅ Parsed {len(alerts)} alerts.")