import subprocess
import json
import datetime

def scrape_tweets(query, max_results=20):
    """
    Scrape tweets using snscrape and return a list of alert-style dicts.
    """
    command = [
        "snscrape", "--jsonl", "--max-results", str(max_results),
        "twitter-search", f"{query} since:{datetime.date.today().isoformat()}"
    ]

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        lines = result.stdout.strip().split('\n')
        alerts = []

        for line in lines:
            tweet = json.loads(line)
            alert = {
                "title": f"Tweet by @{tweet['user']['username']}",
                "summary": tweet["content"],
                "link": tweet["url"],
                "source": "Twitter",
                "region": detect_region(tweet["content"]),
                "language": "en",
                "timestamp": tweet["date"],
            }
            alerts.append(alert)

        return alerts

    except subprocess.CalledProcessError as e:
        print("Error running snscrape:", e)
        print(e.stderr)
        return []

def detect_region(text):
    t = text.lower()
    if "mexico" in t:
        return "Mexico"
    if "ukraine" in t:
        return "Ukraine"
    if "paris" in t or "france" in t:
        return "France"
    if "gaza" in t or "israel" in t:
        return "Middle East"
    return "Global"

# Run test
if __name__ == "__main__":
    test_query = "explosion OR kidnapping OR protest OR gunfire"
    tweet_alerts = scrape_tweets(test_query)
    for alert in tweet_alerts[:5]:
        print(json.dumps(alert, indent=2))
