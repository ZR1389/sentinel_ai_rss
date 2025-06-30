import os
import re
import httpx
import feedparser
from datetime import datetime
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from openai import OpenAI

# -------------------------------
# 🚨 THREAT KEYWORDS
# -------------------------------
THREAT_KEYWORDS = [
    "assassination", "kidnapping", "extortion", "blackmail", "armed robbery", "abduction",
    "violent attack", "missing person", "killing", "murder", "rape", "brutal attack",
    "active shooter", "lone wolf terrorism", "terrorist attack", "terrorists", "terrorism",
    "mass shooter incident", "natural disaster", "emergency", "crisis", "tornado",
    "hurricane", "earthquake", "tsunami", "kidnap for ransom", "physical assault",
    "assassination attempt"
]

KEYWORD_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in THREAT_KEYWORDS) + r')\b',
    re.IGNORECASE
)

# -------------------------------
# 🌐 RSS FEEDS
# -------------------------------
GOOGLE_NEWS_QUERY = (
    "https://news.google.com/rss/search?q="
    "assassination+OR+kidnapping+OR+extortion+OR+blackmail+OR+armed%20robbery+OR+abduction+OR+violent%20attack+OR+missing%20person+OR+"
    "killing+OR+murder+OR+rape+OR+brutal%20attack+OR+active%20shooter+OR+lone%20wolf%20terrorism+OR+terrorist+attack+OR+terrorists+OR+"
    "terrorism+OR+mass%20shooter%20incident+OR+natural%20disaster+OR+emergency+OR+crisis+OR+tornado+OR+hurricane+OR+earthquake+OR+"
    "tsunami+OR+kidnap%20for%20ransom+OR+physical%20assault+OR+assassination%20attempt"
    "&hl=en-US&gl=US&ceid=US:en"
)

FEEDS = [
    "https://travel.state.gov/_res/rss/TW.xml",
    GOOGLE_NEWS_QUERY,
    "https://www.reutersagency.com/feed/?best-topics=conflict-crisis&post_type=best",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://travel.gc.ca/rss/travelalerts.xml",
    "https://www.gov.uk/foreign-travel-advice.atom",
    "https://www.smartraveller.gov.au/consular-services/advice-list/rss",
    "https://www.safetravel.govt.nz/rss.xml",
    "https://www.france24.com/en/rss",
    "https://thehackernews.com/feeds/posts/default",
    "https://www.gdacs.org/xml/rss.xml",
    "https://www.who.int/feeds/entity/csr/don/en/rss.xml"
]

# -------------------------------
# 📦 GPT SETUP (optional summary)
# -------------------------------
load_dotenv()
client = OpenAI()
system_prompt = """
You are Sentinel AI — an intelligent threat analyst created by Zika Rakita, founder of Zika Risk.
You deliver concise, professional threat summaries and actionable advice. Speak with clarity and authority.

If the user is not a subscriber, end with:
“To receive personalized alerts, intelligence briefings, and emergency support, upgrade your access at zikarisk.com.”
"""

def summarize_with_gpt(text):
    try:
        response = client.chat.completions.create(
            model="gpt-4-turbo",
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

# -------------------------------
# 📁 Log summaries (optional)
# -------------------------------
today = datetime.now().strftime("%Y-%m-%d")
log_path = f"logs/sentinel-log-{today}.txt"
os.makedirs("logs", exist_ok=True)

def log_summary(source, title, summary, gpt_summary):
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[Source: {source}]\n")
        f.write(f"Title: {title}\n")
        f.write(f"Raw Summary: {summary[:200]}...\n")
        f.write("AI Summary:\n")
        f.write(gpt_summary + "\n")
        f.write("-" * 60 + "\n\n")

# -------------------------------
# 🔁 FETCH SINGLE FEED
# -------------------------------
def fetch_feed(url, timeout=7):
    try:
        response = httpx.get(url, timeout=timeout)
        if response.status_code != 200:
            print(f"❌ Feed error {response.status_code}: {url}")
            return None, url
        print(f"✅ Fetched: {url}")
        return feedparser.parse(response.content.decode('utf-8', errors='ignore')), url
    except Exception as e:
        print(f"❌ Feed failed: {url}\n   Reason: {e}")
        return None, url

# -------------------------------
# 🧠 MAIN FUNCTION
# -------------------------------
def get_clean_alerts(limit=30, filter_by_keywords=True, region=None, summarize=False):
    alerts = []
    seen = set()

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
            if filter_by_keywords and not KEYWORD_PATTERN.search(full_text):
                continue

            key = f"{title}:{summary}"
            if key in seen:
                continue
            seen.add(key)

            gpt_summary = summarize_with_gpt(full_text) if summarize else None
            if summarize:
                log_summary(source_domain, title, summary, gpt_summary)

            alerts.append({
                "title": title,
                "summary": summary,
                "link": link,
                "source": source_domain,
                "gpt_summary": gpt_summary
            })

            if len(alerts) >= limit:
                return alerts

    if not alerts:
        print("⚠️ No matching alerts found.")
    return alerts

