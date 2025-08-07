import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

# Adjust these columns and features to match your actual plans table schema
plans = [
    # name, price_cents, pdf_reports_per_month, chat_messages_per_month, summaries_per_month, telegram, insights, alerts, darkweb_monitoring, human_security_support, early_access_new_features
    ("FREE", 0, 0, 5, 3, False, False, True, False, False, False),                 # Free: 0 PDFs/mo, 5 chat, 3 summaries, no Telegram
    ("PRO", 4999, 20, 1000, 500, True, True, True, True, False, True),             # Pro: Telegram allowed
    ("ENTERPRISE", 19999, None, 10000, 5000, True, True, True, True, True, True),  # Enterprise: Telegram allowed
]

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()
cur.executemany("""
    INSERT INTO plans (
      name, price_cents, pdf_reports_per_month, chat_messages_per_month, summaries_per_month,
      telegram, insights, alerts, darkweb_monitoring, human_security_support, early_access_new_features
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (name) DO UPDATE SET
      price_cents=EXCLUDED.price_cents,
      pdf_reports_per_month=EXCLUDED.pdf_reports_per_month,
      chat_messages_per_month=EXCLUDED.chat_messages_per_month,
      summaries_per_month=EXCLUDED.summaries_per_month,
      telegram=EXCLUDED.telegram,
      insights=EXCLUDED.insights,
      alerts=EXCLUDED.alerts,
      darkweb_monitoring=EXCLUDED.darkweb_monitoring,
      human_security_support=EXCLUDED.human_security_support,
      early_access_new_features=EXCLUDED.early_access_new_features
""", plans)
conn.commit()
cur.close()
conn.close()
print("Seeded plans!")