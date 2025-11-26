-- Migration: Add weekly digest scheduling system
-- Date: 2025-11-25
-- Description: Enable users to schedule recurring weekly PDF digest emails

-- Create weekly_digest_schedules table
CREATE TABLE IF NOT EXISTS weekly_digest_schedules (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    timezone VARCHAR(50) NOT NULL DEFAULT 'UTC',
    hour INTEGER NOT NULL CHECK (hour >= 0 AND hour <= 23),
    day_of_week INTEGER NOT NULL CHECK (day_of_week >= 0 AND day_of_week <= 6),
    filters JSONB DEFAULT '{}'::jsonb,
    template VARCHAR(50) NOT NULL DEFAULT 'weekly_digest',
    active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW() NOT NULL,
    last_run TIMESTAMP WITHOUT TIME ZONE,
    next_run TIMESTAMP WITHOUT TIME ZONE,
    failure_count INTEGER DEFAULT 0
);

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_weekly_digest_user_id ON weekly_digest_schedules(user_id);
CREATE INDEX IF NOT EXISTS idx_weekly_digest_active ON weekly_digest_schedules(active) WHERE active = true;
CREATE INDEX IF NOT EXISTS idx_weekly_digest_next_run ON weekly_digest_schedules(next_run) WHERE active = true;
CREATE INDEX IF NOT EXISTS idx_weekly_digest_email ON weekly_digest_schedules(email);

-- Add trigger for updated_at
CREATE OR REPLACE FUNCTION update_weekly_digest_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER weekly_digest_updated_at_trigger
BEFORE UPDATE ON weekly_digest_schedules
FOR EACH ROW
EXECUTE FUNCTION update_weekly_digest_updated_at();

-- Add comments for documentation
COMMENT ON TABLE weekly_digest_schedules IS 'User schedules for recurring weekly digest PDF emails';
COMMENT ON COLUMN weekly_digest_schedules.day_of_week IS '0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday, 5=Saturday, 6=Sunday';
COMMENT ON COLUMN weekly_digest_schedules.hour IS 'Hour in users local timezone (0-23)';
COMMENT ON COLUMN weekly_digest_schedules.filters IS 'JSONB filters: {countries: [], severity: [], categories: []}';
COMMENT ON COLUMN weekly_digest_schedules.failure_count IS 'Consecutive failures, disable after 5';

-- Verify table was created
SELECT table_name, column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'weekly_digest_schedules'
ORDER BY ordinal_position;
