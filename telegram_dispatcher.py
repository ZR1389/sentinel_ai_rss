import requests
import os
import json
from datetime import date
from dotenv import load_dotenv
from rss_processor import get_clean_alerts
from threat_scorer import assess_threat_level
import logging

# --- Logging configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TOKEN:
    log.error("TELEGRAM_BOT_TOKEN environment variable is required but not set.")
    raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is required but not set.")
if not CHAT_ID:
    log.error("TELEGRAM_CHAT_ID environment variable is required but not set.")
    raise RuntimeError("TELEGRAM_CHAT_ID environment variable is required but not set.")

RAILWAY_ENV = os.getenv("RAILWAY_ENVIRONMENT")
if RAILWAY_ENV:
    log.info(f"Running in Railway environment: {RAILWAY_ENV}")
else:
    log.info("Running outside Railway or RAILWAY_ENVIRONMENT not set.")

VIP_CLIENTS = [
    str(CHAT_ID),  # Zika default
    # Add more chat IDs as strings if needed
]

SEVERITY_FILTER = {"High", "Critical"}
UNSUBSCRIBE_FILE = "unsubscribed.json"

def load_unsubscribed():
    if not os.path.exists(UNSUBSCRIBE_FILE):
        return set()
    try:
        with open(UNSUBSCRIBE_FILE, "r") as f:
            return set(json.load(f))
    except Exception as e:
        log.error(f"Error loading unsubscribed.json: {e}")
        return set()

def save_unsubscribed(unsubscribed_ids):
    try:
        with open(UNSUBSCRIBE_FILE, "w") as f:
            json.dump(list(unsubscribed_ids), f, indent=2)
    except Exception as e:
        log.error(f"Error saving unsubscribed.json: {e}")

def send_telegram_pdf(pdf_path):
    if not os.path.exists(pdf_path):
        log.error(f"PDF not found: {pdf_path}")
        return

    unsubscribed = load_unsubscribed()
    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"

    for chat_id in VIP_CLIENTS:
        if chat_id in unsubscribed:
            log.info(f"Skipping unsubscribed user: {chat_id}")
            continue

        with open(pdf_path, "rb") as pdf_file:
            files = {"document": pdf_file}
            data = {
                "chat_id": chat_id,
                "caption": f"📄 Sentinel AI Daily Brief — {date.today().isoformat()}"
            }

            try:
                response = requests.post(url, data=data, files=files, timeout=10)
                if response.ok:
                    log.info(f"PDF sent to {chat_id}")
                else:
                    log.error(f"Failed to send PDF to {chat_id}: {response.status_code} — {response.text}")
            except requests.exceptions.RequestException as e:
                log.error(f"Telegram request error for {chat_id}: {e}")

def send_alerts_to_telegram(email="anonymous", limit=10):
    unsubscribed = load_unsubscribed()
    alerts = get_clean_alerts(limit=limit)
    log.info(f"Alerts fetched: {len(alerts)}")

    if not alerts:
        log.warning("No alerts to send.")
        return 0

    qualified_alerts = []
    for alert in alerts:
        # Combine title and summary for risk assessment
        text = f"{alert.get('title', '')}: {alert.get('summary', '')}"
        threat = assess_threat_level(text)
        # Logic fix: threat is a dict, use threat_label field
        threat_label = threat.get("threat_label", "Low")
        if threat_label in SEVERITY_FILTER:
            alert["level"] = threat_label
            alert["threat_score"] = threat.get("score")
            alert["reasoning"] = threat.get("reasoning", "")
            qualified_alerts.append(alert)

    if not qualified_alerts:
        log.warning("No alerts passed the severity filter.")
        return 0

    log.info(f"Sending {len(qualified_alerts)} high-severity alerts to {len(VIP_CLIENTS)} clients...")

    count = 0
    for alert in qualified_alerts:
        message = (
            f"*Sentinel AI High-Risk Alert* — {date.today().isoformat()}\n\n"
            f"*Title:* {alert.get('title', '')}\n"
            f"*Source:* {alert.get('source', '')}\n"
            f"*Threat Level:* {alert.get('level', '')}\n"
            f"*Threat Score:* {alert.get('threat_score', '')}\n"
            f"*Reasoning:* {alert.get('reasoning', '')}\n\n"
            f"{alert.get('summary', '')}\n"
            f"[Read more]({alert.get('link', '')})"
        )

        for chat_id in VIP_CLIENTS:
            if chat_id in unsubscribed:
                log.info(f"Skipping unsubscribed user: {chat_id}")
                continue

            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            }

            try:
                response = requests.post(url, data=payload, timeout=10)
                if response.ok:
                    log.info(f"Alert sent to {chat_id}")
                    count += 1
                else:
                    log.error(f"Failed to send alert to {chat_id}: {response.text}")
            except requests.exceptions.RequestException as e:
                log.error(f"Telegram error for {chat_id}: {e}")

    return count

def handle_unsubscribe(update):
    chat_id = str(update.get("message", {}).get("chat", {}).get("id"))
    text = update.get("message", {}).get("text", "").strip().lower()

    if text == "/stop":
        unsubscribed = load_unsubscribed()
        unsubscribed.add(chat_id)
        save_unsubscribed(unsubscribed)
        log.info(f"User {chat_id} unsubscribed.")
        return {
            "chat_id": chat_id,
            "text": "You have been unsubscribed from Sentinel AI alerts."
        }

    return None

if __name__ == "__main__":
    log.info("Running Telegram dispatcher...")
    count = send_alerts_to_telegram()
    log.info(f"Finished sending {count} alert(s).")