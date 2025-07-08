import feedparser
import json

# Import your feeds from the catalog
from feeds_catalog import LOCAL_FEEDS, GLOBAL_FEEDS  # Add CYBER_FEEDS, COUNTRY_FEEDS if you wish

# Load FCDO feeds from the JSON file
with open('fcdo_country_feeds.json', 'r', encoding='utf-8') as f:
    FCDO_FEEDS = json.load(f)

def check_feed(url):
    try:
        d = feedparser.parse(url)
        if d.get('bozo', False):
            return False, "Parse error"
        if not d.entries:
            return False, "No entries"
        # Optionally, check if any entry is recent (e.g., last 3 months)
        recent = False
        for entry in d.entries:
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                import time
                # Check if published within last 90 days
                if time.mktime(entry.published_parsed) > time.time() - 90 * 24 * 3600:
                    recent = True
                    break
        if not recent:
            return False, "No recent entries"
        return True, "OK"
    except Exception as e:
        return False, str(e)

def check_all_feeds():
    print("Checking LOCAL_FEEDS...")
    for loc, feeds in LOCAL_FEEDS.items():
        for feed in feeds:
            ok, msg = check_feed(feed)
            print(f"LOCAL | {loc} | {feed} | {ok} | {msg}")

    print("\nChecking GLOBAL_FEEDS...")
    for feed in GLOBAL_FEEDS:
        ok, msg = check_feed(feed)
        print(f"GLOBAL | {feed} | {ok} | {msg}")

    # Uncomment if you have CYBER_FEEDS, COUNTRY_FEEDS, etc.
    # from feeds_catalog import CYBER_FEEDS
    # print("\nChecking CYBER_FEEDS...")
    # for feed in CYBER_FEEDS:
    #     ok, msg = check_feed(feed)
    #     print(f"CYBER | {feed} | {ok} | {msg}")

    print("\nChecking FCDO country feeds...")
    for country, feed in FCDO_FEEDS.items():
        ok, msg = check_feed(feed)
        print(f"FCDO | {country} | {feed} | {ok} | {msg}")

if __name__ == "__main__":
    check_all_feeds()