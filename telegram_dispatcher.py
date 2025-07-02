import requests
import os
import json
from datetime import date
from dotenv import load_dotenv
from rss_processor import get_clean_alerts
from threat_scorer import assess_threat_level

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
UNSUBSCRIBED_FILE = "unsubscribed.json"

SEVERITY_FILTER = {"High", "Critical"}

# Load unsubscribed chat IDs
def load_unsubscribed():
    if not os.path.exists(UNSUBSCRIBED_FILE):
        return set()
    with open(UNSUBSCRIBED_FILE, "r") as f:
        return set(json.load(f))

# Save unsubscribed chat IDs
def save_unsubscribed(chat_ids):
    with open(UNSUBSCRIBED_FILE, "w") as f:
        json.dump(list(chat_ids), f)

# Handle incoming /stop commands
def handle_unsubscribe():
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    try:
        response = requests.get(url, timeout=10)
        updates = response.json().get("result", [])
    except Exception as e:
        print("❌ Failed to get updates:", e)
        return set()

    unsubscribed = load_unsubscribed()
    for update in updates:
        msg = update.get("message", {})
        text = msg.get("text", "")
        chat_id = msg.get("chat", {}).get("id")

        if text.strip().lower() == "/stop" and chat_id:
            unsubscribed.add(chat_id)
            print(f"🚫 User {chat_id} unsubscribed")

    save_unsubscribed(unsubscribed)
    return unsubscribed


def send_telegram_pdf(pdf_path):
    unsubscribed = load_unsubscribed()
    if not os.path.exists(pdf_path):
        print(f"❌ PDF not found: {pdf_path}")
        return

    with open(pdf_path, 'rb') as pdf_file:
        files = {'document': pdf_file}
        for chat_id in [CHAT_ID]:  # You can loop multiple here
            if chat_id in unsubscribed:
                print(f"⛔ Skipping unsubscribed chat_id {chat_id}")
                continue

            url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
            data = {
                'chat_id': chat_id,
                'caption': f"📄 Sentinel AI Daily Brief — {date.today().isoformat()}"
            }

            try:
                response = requests.post(url, data=data, files=files, timeout=10)
                if response.ok:
                    print("✅ PDF sent to Telegram")
                else:
                    print("❌ Failed to send PDF:", response.status_code, response.text)
            except requests.exceptions.RequestException as e:
                print("❌ Telegram request failed:", e)


def send_alerts_to_telegram(email="anonymous"):
    unsubscribed = handle_unsubscribe()
    alerts = get_clean_alerts(limit=10)
    if not alerts:
        print("❌ No alerts to send.")
        return 0

    qualified_alerts = []
    for alert in alerts:
        text = f"{alert['title']}: {alert['summary']}"
        level = assess_threat_level(text)
        if level in SEVERITY_FILTER:
            alert["level"] = level
            qualified_alerts.append(alert)

    if not qualified_alerts:
        print("✅ No High/Critical alerts found.")
        return 0

    count = 0
    for alert in qualified_alerts:
        message = (
            f"🛡️ *Sentinel AI High-Risk Alert* — {date.today().isoformat()}\n\n"
            f"*📰 Title:* {alert['title']}\n"
            f"*🌍 Source:* {alert['source']}\n"
            f"*⚠️ Threat Level:* {alert['level']}\n\n"
            f"{alert['summary']}\n"
            f"[🔗 Read more]({alert['link']})"
        )

        for chat_id in [CHAT_ID]:  # You can loop multiple here
            if chat_id in unsubscribed:
                print(f"⛔ Skipping unsubscribed chat_id {chat_id}")
                continue

            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            try:
                response = requests.post(url, data=payload, timeout=10)
                if response.ok:
                    print(f"✅ Alert sent to {chat_id}")
                    count += 1
                else:
                    print(f"❌ Failed to send to {chat_id}: {response.text}")
            except requests.exceptions.RequestException as e:
                print(f"❌ Telegram error for {chat_id}:", e)

    return count
