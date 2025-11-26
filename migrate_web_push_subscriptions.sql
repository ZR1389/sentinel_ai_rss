-- Migration: Web Push Subscriptions table
-- Creates table for storing browser push notification subscriptions (Web Push API)
-- Idempotent: safe to re-run

CREATE TABLE IF NOT EXISTS web_push_subscriptions (
    id SERIAL PRIMARY KEY,
    user_email VARCHAR(255) NOT NULL,
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    user_agent TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

-- Index for fast user lookup
CREATE INDEX IF NOT EXISTS idx_web_push_user_email ON web_push_subscriptions(user_email);

-- Index for cleanup queries
CREATE INDEX IF NOT EXISTS idx_web_push_created_at ON web_push_subscriptions(created_at);

COMMENT ON TABLE web_push_subscriptions IS 'Browser push notification subscriptions (Web Push API with VAPID)';
COMMENT ON COLUMN web_push_subscriptions.endpoint IS 'Push service endpoint URL (unique per browser/device)';
COMMENT ON COLUMN web_push_subscriptions.p256dh IS 'Public key for message encryption (base64)';
COMMENT ON COLUMN web_push_subscriptions.auth IS 'Authentication secret for message encryption (base64)';
COMMENT ON COLUMN web_push_subscriptions.user_agent IS 'Browser user agent for debugging';
