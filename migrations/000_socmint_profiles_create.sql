-- Baseline migration: Create socmint_profiles table for fresh installs
CREATE TABLE IF NOT EXISTS socmint_profiles (
    id SERIAL PRIMARY KEY,
    platform VARCHAR(20) NOT NULL,
    identifier TEXT NOT NULL,
    profile_data JSONB,
    posts_data JSONB,
    scraped_timestamp TIMESTAMP DEFAULT NOW(),
    analysis_status VARCHAR(20) DEFAULT 'pending',
    UNIQUE(platform, identifier)
);

CREATE INDEX IF NOT EXISTS idx_socmint_timestamp ON socmint_profiles(scraped_timestamp);
CREATE INDEX IF NOT EXISTS idx_socmint_status ON socmint_profiles(analysis_status);
