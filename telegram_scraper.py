from telethon.sync import TelegramClient
from datetime import datetime, timedelta, timezone
import json
import os
from dotenv import load_dotenv
from pathlib import Path
import logging

# --- Logging configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

load_dotenv()

# --- Credential loading with safety checks ---
api_id_raw = os.getenv("TELEGRAM_API_ID")
api_hash = os.getenv("TELEGRAM_API_HASH")
session_name = "sentinel_session"

if not api_id_raw:
    log.error("Environment variable TELEGRAM_API_ID is required but not set.")
    raise RuntimeError("Environment variable TELEGRAM_API_ID is required but not set.")
if not api_hash:
    log.error("Environment variable TELEGRAM_API_HASH is required but not set.")
    raise RuntimeError("Environment variable TELEGRAM_API_HASH is required but not set.")
try:
    api_id = int(api_id_raw)
except Exception:
    log.error("TELEGRAM_API_ID must be a valid integer string.")
    raise RuntimeError("TELEGRAM_API_ID must be a valid integer string.")

RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
if RAILWAY_ENV:
    log.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    log.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

channels = [
    "war_monitors", "sentdefender", "noelreports", "tacticalreport", "IntelRepublic",
    "MilitarySummary", "BNOFeed", "vxunderground", "aljazeeraenglish", "cnnbrk", "bbcbreaking"
]

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

CACHE_FILE = "telegram_cache.json"

def load_telegram_cache():
    if Path(CACHE_FILE).exists():
        with open(CACHE_FILE, "r") as f:
            try:
                return json.load(f)
            except Exception as e:
                log.error(f"Failed to load telegram_cache.json: {e}")
                return {}
    return {}

def save_telegram_cache(cache):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        log.error(f"Failed to save telegram_cache.json: {e}")

def detect_region(text):
    t = text.lower() if isinstance(text, str) else str(text).lower()
    if "mexico" in t:
        return "Mexico"
    if "gaza" in t or "israel" in t:
        return "Middle East"
    if "france" in t or "paris" in t:
        return "France"
    if "ukraine" in t:
        return "Ukraine"
    if "russia" in t:
        return "Russia"
    return "Global"

def scrape_telegram_messages():
    alerts = []

    # Only proceed if session file exists (avoid interactive login)
    if not os.path.exists(session_name + ".session"):
        log.warning("Telegram session file not found. Skipping Telegram scraping in production.")
        return []

    cache = load_telegram_cache()
    cache_updated = False

    try:
        with TelegramClient(session_name, api_id, api_hash) as client:
            for username in channels:
                log.info(f"Scraping: {username}")

                # Get last seen post id for this channel, if any
                last_seen_id = cache.get(username)
                new_highest_id = last_seen_id if last_seen_id is not None else 0

                try:
                    entity = client.get_entity(username)
                    messages = client.iter_messages(entity, limit=30)
                    for msg in messages:
                        # Only process messages within the last 24 hours
                        if msg.date < datetime.now(timezone.utc) - timedelta(hours=24):
                            continue
                        if not msg.message:
                            continue

                        # Skip already-seen posts
                        if last_seen_id is not None and msg.id <= last_seen_id:
                            continue

                        content = msg.message.lower() if isinstance(msg.message, str) else str(msg.message).lower()
                        if any(keyword in content for keyword in THREAT_KEYWORDS):
                            alerts.append({
                                "title": f"Telegram Post: {username}",
                                "summary": msg.message,
                                "link": f"https://t.me/{username}/{msg.id}",
                                "source": "Telegram",
                                "region": detect_region(msg.message),
                                "timestamp": msg.date.isoformat(),
                                "post_id": msg.id
                            })

                        # Track the highest post ID seen this run
                        if msg.id > new_highest_id:
                            new_highest_id = msg.id

                    # Only update cache if we found something higher than last_seen_id
                    if new_highest_id and (last_seen_id is None or new_highest_id > last_seen_id):
                        cache[username] = new_highest_id
                        cache_updated = True

                except Exception as e:
                    log.error(f"Error scraping {username}: {e}")

    except Exception as e:
        log.error(f"Telegram client setup failed: {e}")
        return []

    if cache_updated:
        save_telegram_cache(cache)

    return alerts

if __name__ == "__main__":
    alerts = scrape_telegram_messages()
    if alerts:
        log.info(f"Found {len(alerts)} new alerts")
        for a in alerts[:5]:
            print(json.dumps(a, indent=2))
    else:
        log.info("No new matching alerts found in the last 24 hours.")