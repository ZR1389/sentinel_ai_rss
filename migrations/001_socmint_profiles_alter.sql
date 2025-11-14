-- Alter existing socmint_profiles to new schema
ALTER TABLE socmint_profiles ADD COLUMN IF NOT EXISTS identifier TEXT;
UPDATE socmint_profiles SET identifier = COALESCE(profile_url, username) WHERE identifier IS NULL;

ALTER TABLE socmint_profiles ADD COLUMN IF NOT EXISTS profile_data JSONB;
ALTER TABLE socmint_profiles ADD COLUMN IF NOT EXISTS posts_data JSONB;

ALTER TABLE socmint_profiles ADD COLUMN IF NOT EXISTS scraped_timestamp TIMESTAMP;
UPDATE socmint_profiles SET scraped_timestamp = scraped_at WHERE scraped_timestamp IS NULL;

ALTER TABLE socmint_profiles ADD COLUMN IF NOT EXISTS analysis_status VARCHAR(20) DEFAULT 'pending';

-- Ensure uniqueness across platform + identifier via unique index
CREATE UNIQUE INDEX IF NOT EXISTS socmint_unique_platform_identifier ON socmint_profiles(platform, identifier);

-- Supporting indexes
CREATE INDEX IF NOT EXISTS idx_socmint_timestamp ON socmint_profiles(scraped_timestamp);
CREATE INDEX IF NOT EXISTS idx_socmint_status ON socmint_profiles(analysis_status);
