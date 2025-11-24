-- Migration: Add trial email tracking table
-- This table tracks which trial reminder emails have been sent to prevent duplicates

CREATE TABLE IF NOT EXISTS trial_emails_sent (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email_type VARCHAR(50) NOT NULL,  -- 'day_1', 'day_3', 'day_5', 'day_6'
    sent_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, email_type)
);

CREATE INDEX idx_trial_emails_user_id ON trial_emails_sent(user_id);
CREATE INDEX idx_trial_emails_sent_at ON trial_emails_sent(sent_at);

COMMENT ON TABLE trial_emails_sent IS 'Tracks trial reminder emails sent to users';
COMMENT ON COLUMN trial_emails_sent.email_type IS 'Type of reminder: day_1, day_3, day_5, day_6';
