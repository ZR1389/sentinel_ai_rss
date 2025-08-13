import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

plans = [
    # name, price_cents, chat_messages_per_month
    ("FREE", 0, 3),
    ("PRO", 4900, 1000),         # $49.00
    ("ENTERPRISE", 49900, 10000) # $499.00
]

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()
cur.executemany("""
    INSERT INTO plans (
      name, price_cents, chat_messages_per_month
    ) VALUES (%s, %s, %s)
    ON CONFLICT (name) DO UPDATE SET
      price_cents=EXCLUDED.price_cents,
      chat_messages_per_month=EXCLUDED.chat_messages_per_month
""", plans)
conn.commit()
cur.close()
conn.close()
print("Seeded chat-only plans!")