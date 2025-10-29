import feedparser
from db_utils import save_raw_alerts_to_db
import uuid
from datetime import datetime, timezone

FEEDS = [
    "https://krebsonsecurity.com/feed/",
    "https://www.cisa.gov/news.xml",
    "https://www.kyivpost.com/feed",
    "https://www.jpost.com/rss/rssfeedsfrontpage.aspx",
    "https://thenationonlineng.net/feed/",
    "https://www.nation.co.ke/rss.xml",
    "https://www.thejakartapost.com/rss",
    "https://www.bangkokpost.com/rss/data/topstories.xml",
]

all_alerts = []
for feed_url in FEEDS:
    print(f"Fetching: {feed_url}")
    feed = feedparser.parse(feed_url)
    for entry in feed.entries[:10]:
        all_alerts.append({
            "uuid": str(uuid.uuid4()),
            "title": entry.get("title", "")[:200],
            "summary": entry.get("summary", "")[:1000],
            "link": entry.get("link", ""),
            "source": feed_url.split('/')[2],
            "published": datetime.now(timezone.utc),
            "country": "Global",
            "tags": ["security"]
        })

if all_alerts:
    wrote = save_raw_alerts_to_db(all_alerts)
    print(f"\n✅ Wrote {wrote} alerts to database")
