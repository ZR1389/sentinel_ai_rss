import requests
import os
import json
from datetime import date
from dotenv import load_dotenv
from threat_engine import get_clean_alerts
from threat_scorer import assess_threat_level
from plan_utils import get_plan_limits, require_plan_feature, check_user_pdf_quota, increment_user_pdf_usage
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

# List of Telegram chat IDs to receive alerts
TELEGRAM_TARGET_CHAT_IDS = [
    str(CHAT_ID),
    # Add more chat IDs as needed
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

def send_telegram_pdf(pdf_path, email=None):
    if not os.path.exists(pdf_path):
        log.error(f"PDF not found: {pdf_path}")
        return

    # --- ENFORCE PLAN GATING ---
    if email:
        plan_limits = get_plan_limits(email)
        if not plan_limits.get("telegram"):
            log.info(f"User {email} not allowed to send Telegram PDF (feature gated).")
            return

        allowed, reason = check_user_pdf_quota(email, plan_limits)
        if not allowed:
            log.info(f"User {email} has reached their monthly PDF quota for Telegram: {reason}")
            return

    unsubscribed = load_unsubscribed()
    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"

    sent = False
    for chat_id in TELEGRAM_TARGET_CHAT_IDS:
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
                    sent = True
                else:
                    log.error(f"Failed to send PDF to {chat_id}: {response.status_code} — {response.text}")
            except requests.exceptions.RequestException as e:
                log.error(f"Telegram request error for {chat_id}: {e}")

    # Increment usage after successful send
    if sent and email:
        increment_user_pdf_usage(email)

def send_alerts_to_telegram(email="anonymous", limit=10):
    # --- ENFORCE PLAN GATING ONLY ---
    if not email:
        log.info("No email provided for Telegram alert dispatch.")
        return 0

    plan_limits = get_plan_limits(email)
    if not plan_limits.get("telegram"):
        log.info(f"User {email} not allowed to send Telegram alerts (feature gated).")
        return 0

    unsubscribed = load_unsubscribed()
    alerts = get_clean_alerts(limit=limit)
    log.info(f"Alerts fetched: {len(alerts)}")

    if not alerts:
        log.warning("No alerts to send.")
        return 0

    qualified_alerts = []
    for alert in alerts:
        text = f"{alert.get('title', '')}: {alert.get('summary', '')}"
        threat = assess_threat_level(text)
        threat_label = threat.get("threat_label", "Low")
        if threat_label in SEVERITY_FILTER:
            alert["level"] = threat_label
            alert["threat_score"] = threat.get("score")
            alert["reasoning"] = threat.get("reasoning", "")
            qualified_alerts.append(alert)

    if not qualified_alerts:
        log.warning("No alerts passed the severity filter.")
        return 0

    log.info(f"Sending {len(qualified_alerts)} high-severity alerts to {len(TELEGRAM_TARGET_CHAT_IDS)} clients...")

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

        for chat_id in TELEGRAM_TARGET_CHAT_IDS:
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
    test_email = os.getenv("TEST_USER_EMAIL", "anonymous")
    count = send_alerts_to_telegram(email=test_email)
    log.info(f"Finished sending {count} alert(s).")