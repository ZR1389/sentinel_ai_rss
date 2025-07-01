import requests
import os
from datetime import date
from dotenv import load_dotenv
from rss_processor import get_clean_alerts
from threat_scorer import assess_threat_level

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ✅ You can later map email to chat_ids if needed
VIP_CLIENTS = [
    CHAT_ID,  # Zika default
    # "123456789",  # Add more client chat_ids here
]

SEVERITY_FILTER = {"High", "Critical"}


def send_telegram_pdf(pdf_path):
    if not os.path.exists(pdf_path):
        print(f"❌ PDF not found: {pdf_path}")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendDocument"
    with open(pdf_path, 'rb') as pdf_file:
        files = {'document': pdf_file}
        data = {
            'chat_id': CHAT_ID,
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

        for chat_id in VIP_CLIENTS:
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


