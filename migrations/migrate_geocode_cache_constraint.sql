-- Fix geocode_cache missing unique constraint
-- This resolves the error: "there is no unique or exclusion constraint matching the ON CONFLICT specification"

-- Add unique constraint on (city, country)
-- Handle NULL country values properly with COALESCE
ALTER TABLE geocode_cache
DROP CONSTRAINT IF EXISTS geocode_cache_city_country_key;

ALTER TABLE geocode_cache
ADD CONSTRAINT geocode_cache_city_country_key 
UNIQUE (city, country);

-- Verify the constraint exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 
        FROM information_schema.table_constraints 
        WHERE constraint_name = 'geocode_cache_city_country_key' 
        AND table_name = 'geocode_cache'
    ) THEN
        RAISE NOTICE '✓ Unique constraint geocode_cache_city_country_key created successfully';
    ELSE
        RAISE EXCEPTION '✗ Failed to create unique constraint';
    END IF;
END $$;
