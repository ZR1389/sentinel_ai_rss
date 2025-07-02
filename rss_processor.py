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
    "crime", "violence", "terrorism", "attack", "kidnapping", "abduction", "natural disaster",
    "earthquake", "tsunami", "hurricane", "extortion", "shooting", "mass killing", "murder", "cyberattack"
]

KEYWORD_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in THREAT_KEYWORDS) + r')\b',
    re.IGNORECASE
)

# -------------------------------
# 🌐 RSS FEEDS
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
# 🧠 GPT SETUP
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
        if label not in [
            "Terrorism", "Protest", "Crime", "Kidnapping", "Cyber",
            "Natural Disaster", "Political", "Infrastructure", "Health", "Unclassified"
        ]:
            return "Unclassified"
        return label
    except Exception as e:
        print(f"❌ Threat type classification error: {e}")
        return "Unclassified"

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

def get_clean_alerts(region=None, topic=None, limit=20, summarize=False):
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
                print(f"✅ Parsed {len(alerts)} alerts.")
                return alerts

    print(f"✅ Parsed {len(alerts)} alerts.")
    return alerts
