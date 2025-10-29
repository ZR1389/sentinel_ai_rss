import psycopg2
from dotenv import load_dotenv
import os

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# CREATE ALL TABLES (AUTH + RSS/THREAT SYSTEM)
schema = """
-- ============================================================
-- AUTH TABLES
-- ============================================================

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

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_plan ON users(plan);

CREATE TABLE IF NOT EXISTS user_usage (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    chat_messages_used INTEGER DEFAULT 0,
    chat_messages_limit INTEGER DEFAULT 3,
    last_reset TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS email_verification_codes (
    email TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    attempts INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS security_events (
    id SERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    email TEXT,
    ip_address TEXT,
    user_agent TEXT,
    endpoint TEXT,
    details TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_security_events_email ON security_events(email);
CREATE INDEX IF NOT EXISTS idx_security_events_created ON security_events(created_at);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    refresh_id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_email ON refresh_tokens(email);

-- ============================================================
-- RSS / THREAT INTELLIGENCE TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS raw_alerts (
    id SERIAL PRIMARY KEY,
    uuid TEXT UNIQUE NOT NULL,
    title TEXT,
    summary TEXT,
    en_snippet TEXT,
    link TEXT,
    source TEXT,
    published TIMESTAMP,
    tags JSONB DEFAULT '[]'::jsonb,
    region TEXT,
    country TEXT,
    city TEXT,
    language TEXT,
    latitude NUMERIC,
    longitude NUMERIC,
    fetched_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_raw_alerts_uuid ON raw_alerts(uuid);
CREATE INDEX IF NOT EXISTS idx_raw_alerts_country ON raw_alerts(country);
CREATE INDEX IF NOT EXISTS idx_raw_alerts_city ON raw_alerts(city);
CREATE INDEX IF NOT EXISTS idx_raw_alerts_published ON raw_alerts(published);
CREATE INDEX IF NOT EXISTS idx_raw_alerts_created ON raw_alerts(created_at);

CREATE TABLE IF NOT EXISTS alerts (
    id SERIAL PRIMARY KEY,
    uuid TEXT UNIQUE NOT NULL,
    title TEXT,
    summary TEXT,
    link TEXT,
    source TEXT,
    published TIMESTAMP,
    region TEXT,
    country TEXT,
    city TEXT,
    latitude NUMERIC,
    longitude NUMERIC,
    category TEXT,
    subcategory TEXT,
    score NUMERIC DEFAULT 0,
    label TEXT,
    confidence NUMERIC DEFAULT 0,
    domains JSONB DEFAULT '[]'::jsonb,
    sources JSONB DEFAULT '[]'::jsonb,
    baseline_ratio NUMERIC,
    trend_direction TEXT,
    incident_count_30d INTEGER DEFAULT 0,
    anomaly_flag BOOLEAN DEFAULT FALSE,
    future_risk_probability NUMERIC,
    cluster_id TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alerts_uuid ON alerts(uuid);
CREATE INDEX IF NOT EXISTS idx_alerts_country ON alerts(country);
CREATE INDEX IF NOT EXISTS idx_alerts_city ON alerts(city);
CREATE INDEX IF NOT EXISTS idx_alerts_category ON alerts(category);
CREATE INDEX IF NOT EXISTS idx_alerts_score ON alerts(score);
CREATE INDEX IF NOT EXISTS idx_alerts_published ON alerts(published);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at);

CREATE TABLE IF NOT EXISTS email_alerts (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL,
    alert_id INTEGER REFERENCES alerts(id) ON DELETE CASCADE,
    sent_at TIMESTAMP DEFAULT NOW(),
    status TEXT DEFAULT 'sent'
);

CREATE INDEX IF NOT EXISTS idx_email_alerts_email ON email_alerts(email);
CREATE INDEX IF NOT EXISTS idx_email_alerts_sent ON email_alerts(sent_at);

-- ============================================================
-- SUPPORTING TABLES (from your system)
-- ============================================================

CREATE TABLE IF NOT EXISTS geocode_cache (
    id SERIAL PRIMARY KEY,
    city TEXT NOT NULL,
    country TEXT,
    lat NUMERIC,
    lon NUMERIC,
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_geocode_city_country ON geocode_cache(city, country);

CREATE TABLE IF NOT EXISTS feed_health (
    id SERIAL PRIMARY KEY,
    feed_url TEXT UNIQUE NOT NULL,
    host TEXT,
    last_status INTEGER,
    last_error TEXT,
    last_ok TIMESTAMP,
    last_checked TIMESTAMP DEFAULT NOW(),
    ok_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    avg_latency_ms NUMERIC,
    consecutive_fail INTEGER DEFAULT 0,
    backoff_until TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_feed_health_url ON feed_health(feed_url);
CREATE INDEX IF NOT EXISTS idx_feed_health_host ON feed_health(host);

-- ============================================================
-- TRIGGERS
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$ 
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_usage_updated_at BEFORE UPDATE ON user_usage
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_alerts_updated_at BEFORE UPDATE ON alerts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
"""

cur.execute(schema)
conn.commit()
print("✅ All tables created (Auth + RSS/Threat)!")

# SEED PLANS
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

# VERIFY
cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
tables = [row[0] for row in cur.fetchall()]
print(f"✅ Total tables: {len(tables)}")
print(f"   Tables: {', '.join(tables)}")

cur.close()
conn.close()