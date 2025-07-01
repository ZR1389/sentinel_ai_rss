import schedule
import time
from datetime import datetime
from email_dispatcher import send_pdf_report
from telegram_dispatcher import send_alerts_to_telegram
import json

print(f"🔄 Sentinel AI Scheduler started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# ✅ Load client list (email + plan)
with open("clients.json") as f:
    clients = json.load(f)

# ✅ Email job
def email_job():
    print("📩 Running email dispatch...")
    for client in clients:
        email = client.get("email", "")
        plan = client.get("plan", "FREE").upper()
        if plan in ["PRO", "VIP"]:
            try:
                send_pdf_report(email=email, plan=plan)
                print(f"✅ Sent report to {email}")
            except Exception as e:
                print(f"❌ Failed for {email}: {str(e)}")

# ✅ Telegram job
def telegram_job():
    print("📲 Running Telegram dispatch...")
    try:
        count = send_alerts_to_telegram()
        print(f"✅ Sent {count} Telegram alerts.")
    except Exception as e:
        print(f"❌ Telegram dispatch failed: {str(e)}")

# ✅ Schedule both daily at 08:00
schedule.every().day.at("08:00").do(email_job)
schedule.every().day.at("08:00").do(telegram_job)

# ✅ Run loop
while True:
    schedule.run_pending()
    time.sleep(30)
