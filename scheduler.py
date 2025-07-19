import os
from datetime import datetime
from dotenv import load_dotenv
from rss_processor import get_clean_alerts

load_dotenv()
print(f"📅 Sentinel AI Ingestion (Railway Service) started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

def ingestion_job():
    print(f"\n⏰ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running RSS ingestion job (hourly)...")
    try:
        alerts = get_clean_alerts(
            region=None,
            topic=None,
            city=None,
            limit=100,  # adjust as needed
            summarize=True,
            user_email="system-ingest@sentinel",
            session_id="scheduler-ingest",
            use_telegram=True,
            write_to_db=True
        )
        print(f"✅ Ingestion completed, alerts processed: {len(alerts)}")
    except Exception as e:
        print(f"❌ Ingestion job failed: {e}")

if __name__ == "__main__":
    # Optional: warn if not running in Railway/service context
    if not os.getenv("RAILWAY_ENVIRONMENT"):
        print("⚠️  Not running in a Railway environment! Make sure environment variables are set.")
    ingestion_job()