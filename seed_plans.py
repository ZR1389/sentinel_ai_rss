import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

plans = [
    # name, price_cents, messages_per_month, summaries_per_month, chat_messages_per_month, travel_alerts_per_month,
    # access_to_all_features, response_speed, personalized_insights_frequency,
    # darkweb_monitoring, human_security_support, custom_pdf_briefings_frequency, early_access_new_features,
    # pdf_report, telegram_alerts, insights, alerts
    ("FREE", 0, 30, 10, 30, 0, False, "Standard", "Monthly", False, False, None, False, False, False, True, True),
    ("BASIC", 1999, 100, 50, 100, 25, False, "Standard", "Monthly", False, False, None, False, False, True, True, True),
    ("PRO", 4999, 1000, 500, 1000, 100, True, "Fast", "Weekly", True, False, "Monthly", True, True, True, True, True),
    ("VIP", 14999, 10000, 5000, 10000, 1000, True, "Fastest", "On-demand", True, True, "On-request", True, True, True, True, True),
]

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()
cur.executemany("""
    INSERT INTO plans (
      name, price_cents, messages_per_month, summaries_per_month, chat_messages_per_month, travel_alerts_per_month,
      access_to_all_features, response_speed, personalized_insights_frequency,
      darkweb_monitoring, human_security_support, custom_pdf_briefings_frequency, early_access_new_features,
      pdf_report, telegram_alerts, insights, alerts
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (name) DO NOTHING
""", plans)
conn.commit()
cur.close()
conn.close()
print("Seeded plans!")