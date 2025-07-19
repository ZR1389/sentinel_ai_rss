import os
import requests
from bs4 import BeautifulSoup
import json
import logging

# --- Logging configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
if RAILWAY_ENV:
    log.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    log.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

BASE_URL = "https://www.gov.uk"
TRAVEL_ADVICE_URL = f"{BASE_URL}/foreign-travel-advice"

def get_country_feeds():
    resp = requests.get(TRAVEL_ADVICE_URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    country_feeds = {}

    for a in soup.select("a[href^='/foreign-travel-advice/']"):
        path = a['href']
        if path.endswith('.atom'):
            continue
        slug = path.split('/foreign-travel-advice/')[-1].strip("/")
        name = a.get_text(strip=True)
        feed_url = BASE_URL + path + ".atom"
        if slug and name and not feed_url.endswith("/foreign-travel-advice.atom"):
            country_feeds[name] = feed_url

    return country_feeds

if __name__ == "__main__":
    try:
        feeds = get_country_feeds()
        with open("fcdo_country_feeds.json", "w", encoding="utf-8") as f:
            json.dump(feeds, f, indent=2, ensure_ascii=False)
        log.info(f"Saved {len(feeds)} feeds to fcdo_country_feeds.json")
        log.info("Sample feeds:")
        for k in list(feeds.keys())[:10]:
            log.info(f"{k}: {feeds[k]}")
        log.info(f"Total countries/territories: {len(feeds)}")
        log.info("All feeds saved to fcdo_country_feeds.json")
    except Exception as e:
        log.error(f"Error fetching or saving FCDO feeds: {e}")