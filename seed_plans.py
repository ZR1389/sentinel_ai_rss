import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# CREATE TABLES FIRST
schema = """
CREATE TABLE IF NOT EXISTS plans (
    name TEXT PRIMARY KEY,
    price_cents INTEGER NOT NULL,
    chat_messages_per_month INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    plan TEXT DEFAULT 'FREE' REFERENCES plans(name),
    name TEXT,
    employer TEXT,
    email_verified BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    preferred_region TEXT,
    preferred_threat_type TEXT,
    home_location TEXT,
    extra_details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_usage (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    chat_messages_used INTEGER DEFAULT 0,
    chat_messages_limit INTEGER DEFAULT 3,
    last_reset TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS email_verification_codes (
    email TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    attempts INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

cur.execute(schema)
conn.commit()
print("✅ Tables created!")

# NOW SEED PLANS
plans = [
    ("FREE", 0, 3),
    ("PRO", 4900, 1000),
    ("ENTERPRISE", 49900, 10000)
]

cur.executemany("""
    INSERT INTO plans (name, price_cents, chat_messages_per_month)
    VALUES (%s, %s, %s)
    ON CONFLICT (name) DO UPDATE SET
      price_cents=EXCLUDED.price_cents,
      chat_messages_per_month=EXCLUDED.chat_messages_per_month
""", plans)
conn.commit()

print("✅ Seeded plans!")
cur.close()
conn.close()