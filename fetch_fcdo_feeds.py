import requests
from bs4 import BeautifulSoup
import json

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
        # Get country slug
        slug = path.split('/foreign-travel-advice/')[-1].strip("/")
        # Get country name (text)
        name = a.get_text(strip=True)
        # Build atom feed url
        feed_url = BASE_URL + path + ".atom"
        # Avoid duplicates and only add real country links (skip main page link)
        if slug and name and not feed_url.endswith("/foreign-travel-advice.atom"):
            country_feeds[name] = feed_url

    return country_feeds

if __name__ == "__main__":
    feeds = get_country_feeds()
    # Save as JSON
    with open("fcdo_country_feeds.json", "w", encoding="utf-8") as f:
        json.dump(feeds, f, indent=2, ensure_ascii=False)
    # Print sample
    print("Sample feeds:")
    for k in list(feeds.keys())[:10]:
        print(f"{k}: {feeds[k]}")
    print(f"\nTotal countries/territories: {len(feeds)}")
    print("All feeds saved to fcdo_country_feeds.json")