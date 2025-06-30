import requests
from datetime import datetime
from rss_processor import get_clean_alerts
from threat_scorer import assess_threat_level

# Telegram Bot config
TOKEN = "7980684217:AAGs4kWNrFVpkvzU0GdsnIKZpI7kl_3NPBg"

# ✅ Add multiple recipient chat IDs
VIP_CLIENTS = [
    "7081882584",  # Zika's chat ID
    # "123456789", # Add more client chat_ids here
]

# ✅ Only send HIGH or CRITICAL alerts
SEVERITY_FILTER = {"High", "Critical"}

# ✅ Get top alerts (you can increase limit)
alerts = get_clean_alerts(limit=10)

if not alerts:
    print("❌ No alerts to send.")
    exit()

# ✅ Filter high-severity alerts
qualified_alerts = []
for alert in alerts:
    text = f"{alert['title']}: {alert['summary']}"
    level = assess_threat_level(text)
    if level in SEVERITY_FILTER:
        alert["level"] = level
        qualified_alerts.append(alert)

if not qualified_alerts:
    print("✅ No High/Critical alerts found. No messages sent.")
    exit()

# ✅ Format and send alerts
def send_telegram_message(chat_id, msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": msg,
        "parse_mode": "Markdown"
    }
    response = requests.post(url, data=payload)
    if response.ok:
        print(f"✅ Alert sent to Telegram user {chat_id}")
    else:
        print(f"❌ Failed to send to {chat_id}: {response.text}")

# ✅ Compose and dispatch all alerts
for alert in qualified_alerts:
    message = (
        f"🛡️ *Sentinel AI High-Risk Alert* — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        f"*📰 Title:* {alert['title']}\n"
        f"*🌍 Source:* {alert['source']}\n"
        f"*⚠️ Threat Level:* {alert['level']}\n\n"
        f"{alert['summary']}\n"
        f"[🔗 Read more]({alert['link']})"
    )

    for chat_id in VIP_CLIENTS:
        send_telegram_message(chat_id, message)

