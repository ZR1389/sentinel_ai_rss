from telethon.sync import TelegramClient
from telethon.tl.types import PeerChannel
from datetime import datetime, timedelta, timezone
import json
import os

# Your API credentials
api_id = 25094393
api_hash = 'c9f39c23e0d33cd825b2918d99346cb9'

# Session file name
session_name = "sentinel_session"

channels = [
    "war_monitors",
    "sentdefender",
    "noelreports",
    "tacticalreport",
    "IntelRepublic",
    "MilitarySummary",
    "BNOFeed",
    "vxunderground",
    "aljazeeraenglish",
    "cnnbrk",
    "bbcbreaking"
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
    try:
        if not os.path.exists(session_name + ".session"):
            print("⚠️ Telegram session file not found. Skipping Telegram scraping in production.")
            return []

        with TelegramClient(session_name, api_id, api_hash) as client:
            for username in channels:
                print(f"Scraping channel: {username}")
                try:
                    entity = client.get_entity(username)
                    messages = client.iter_messages(entity, limit=30)

                    for msg in messages:
                        if msg.date < datetime.now(timezone.utc) - timedelta(hours=24):
                            continue
                        if msg.message:
                            content = msg.message.lower() if isinstance(msg.message, str) else str(msg.message).lower()
                            if any(k.lower() in content for k in THREAT_KEYWORDS):
                                alert = {
                                    "title": f"Telegram Post: {username}",
                                    "summary": msg.message,
                                    "link": f"https://t.me/{username}/{msg.id}",
                                    "source": "Telegram",
                                    "region": detect_region(msg.message),
                                    "language": "en",
                                    "timestamp": msg.date.isoformat()
                                }
                                alerts.append(alert)
                except Exception as e:
                    print(f"Error with channel {username}: {e}")
    except Exception as e:
        print(f"Telegram client setup failed: {e}")
        return []

    return alerts

if __name__ == "__main__":
    alerts = scrape_telegram_messages()
    if alerts:
        for a in alerts[:5]:
            print(json.dumps(a, indent=2))
    else:
        print("No matching alerts found. Try different channels or wait for new posts.")