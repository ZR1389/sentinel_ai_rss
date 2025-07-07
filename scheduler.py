import schedule
import time
import json
from datetime import datetime
from email_dispatcher import send_pdf_report
from telegram_dispatcher import send_alerts_to_telegram

print(f"📅 Sentinel AI Scheduler started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

def email_job():
    print(f"\n⏰ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running email dispatch...")
    try:
        with open("clients.json", "r") as f:
            clients = json.load(f)
    except Exception as e:
        print(f"❌ Failed to load clients.json: {e}")
        return

    for client in clients:
        email = client.get("email", "")
        plan = client.get("plan", "FREE").upper()

        if plan in ["PRO", "VIP"]:
            try:
                send_pdf_report(email=email, plan=plan)
                print(f"✅ Report sent to {email}")
            except Exception as e:
                print(f"❌ Error for {email}: {e}")
        else:
            print(f"⏩ Skipped {email} (Plan: {plan}) — No PDF access")

def telegram_job():
    print(f"\n⏰ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running Telegram dispatch...")
    try:
        count = send_alerts_to_telegram()
        print(f"📨 Sent {count} Telegram alerts.")
    except Exception as e:
        print(f"❌ Telegram dispatch failed: {e}")

# Schedule jobs daily at 08:00
schedule.every().day.at("08:00").do(email_job)
schedule.every().day.at("08:00").do(telegram_job)

# Main loop
try:
    while True:
        schedule.run_pending()
        time.sleep(30)
except KeyboardInterrupt:
    print("\n🛑 Scheduler stopped by user.")