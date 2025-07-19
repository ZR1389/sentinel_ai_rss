import os
from datetime import datetime
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import DictCursor
from email_dispatcher import send_pdf_report
from telegram_dispatcher import send_alerts_to_telegram

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

def get_users_with_feature(feature_column):
    if not DATABASE_URL:
        print("❌ DATABASE_URL environment variable not set.")
        return []
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=DictCursor)
        cur = conn.cursor()
        cur.execute(f"""
            SELECT u.email, u.plan
            FROM users u
            JOIN plans p ON u.plan = p.name
            WHERE p.{feature_column} = TRUE
        """)
        users = cur.fetchall()
        cur.close()
        conn.close()
        return users
    except Exception as e:
        print(f"❌ Database query failed: {e}")
        return []

def email_job():
    print(f"\n⏰ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running email dispatch (daily 08:00)...")
    clients = get_users_with_feature('pdf_report')
    if not clients:
        print("⚠️ No users eligible for PDF reports.")
        return

    for client in clients:
        email = client["email"]
        plan = client["plan"]
        result = send_pdf_report(email=email, plan=plan)
        status = result.get("status", "unknown")
        reason = result.get("reason", "")
        if status == "sent":
            print(f"✅ Report sent to {email} ({plan})")
        elif status == "skipped":
            print(f"⏩ Skipped {email} ({plan}) — {reason}")
        elif status == "error":
            print(f"❌ Error for {email} ({plan}): {reason}")
        else:
            print(f"❓ Unknown status for {email} ({plan}): {result}")

def telegram_job():
    print(f"\n⏰ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running Telegram dispatch (daily 08:00)...")
    clients = get_users_with_feature('telegram_alerts')
    if not clients:
        print("⚠️ No users eligible for Telegram alerts.")
        return

    for client in clients:
        email = client["email"]
        plan = client["plan"]
        try:
            count = send_alerts_to_telegram(email=email, plan=plan)
            print(f"📨 Sent Telegram alert to {email} ({plan}).")
        except Exception as e:
            print(f"❌ Telegram dispatch failed for {email} ({plan}): {e}")

if __name__ == "__main__":
    print(f"📅 Sentinel AI Notifications (Railway Service) started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if not os.getenv("RAILWAY_ENVIRONMENT"):
        print("⚠️  Not running in a Railway environment! Make sure environment variables are set.")
    email_job()
    telegram_job()