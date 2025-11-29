-- Database Performance Optimization: Add Counter Columns
-- This migration adds denormalized counter columns to avoid expensive COUNT(*) queries

-- 1. Add thread_messages_count to chat_threads
-- This eliminates the need for COUNT(*) queries on chat_messages when checking message limits
ALTER TABLE chat_threads 
ADD COLUMN IF NOT EXISTS thread_messages_count INTEGER DEFAULT 0 NOT NULL;

-- Backfill existing threads with accurate counts
UPDATE chat_threads ct
SET thread_messages_count = (
    SELECT COUNT(*) 
    FROM chat_messages cm 
    WHERE cm.thread_id = ct.id
)
WHERE thread_messages_count = 0;

-- Create index for efficient queries filtering by message count
CREATE INDEX IF NOT EXISTS idx_chat_threads_messages_count 
ON chat_threads(user_id, thread_messages_count) 
WHERE is_deleted = FALSE;

COMMENT ON COLUMN chat_threads.thread_messages_count IS 
'Denormalized count of messages in thread. Updated on insert/delete of chat_messages for performance.';

-- 2. Add destinations_count to travel_itineraries
-- This eliminates the need to parse JSONB waypoints array when checking destination limits
ALTER TABLE travel_itineraries 
ADD COLUMN IF NOT EXISTS destinations_count INTEGER DEFAULT 0 NOT NULL;

-- Backfill existing itineraries by counting waypoints in JSONB data
UPDATE travel_itineraries
SET destinations_count = (
    CASE 
        WHEN data->'waypoints' IS NOT NULL 
        THEN jsonb_array_length(data->'waypoints')
        ELSE 0
    END
)
WHERE destinations_count = 0;

-- Create index for efficient queries filtering by destination count
CREATE INDEX IF NOT EXISTS idx_travel_itineraries_destinations_count 
ON travel_itineraries(user_id, destinations_count) 
WHERE is_deleted = FALSE;

COMMENT ON COLUMN travel_itineraries.destinations_count IS 
'Denormalized count of waypoints/destinations. Extracted from data->waypoints for performance.';

-- 3. Verify counts match for audit purposes
DO $$
DECLARE
    thread_mismatches INTEGER;
    itinerary_mismatches INTEGER;
BEGIN
    -- Check chat_threads accuracy
    SELECT COUNT(*) INTO thread_mismatches
    FROM chat_threads ct
    WHERE ct.thread_messages_count != (
        SELECT COUNT(*) FROM chat_messages cm WHERE cm.thread_id = ct.id
    );
    
    IF thread_mismatches > 0 THEN
        RAISE NOTICE 'WARNING: % chat_threads have mismatched message counts', thread_mismatches;
    ELSE
        RAISE NOTICE 'SUCCESS: All chat_threads message counts are accurate';
    END IF;
    
    -- Check travel_itineraries accuracy
    SELECT COUNT(*) INTO itinerary_mismatches
    FROM travel_itineraries
    WHERE destinations_count != (
        CASE 
            WHEN data->'waypoints' IS NOT NULL 
            THEN jsonb_array_length(data->'waypoints')
            ELSE 0
        END
    );
    
    IF itinerary_mismatches > 0 THEN
        RAISE NOTICE 'WARNING: % travel_itineraries have mismatched destination counts', itinerary_mismatches;
    ELSE
        RAISE NOTICE 'SUCCESS: All travel_itineraries destination counts are accurate';
    END IF;
END $$;

-- Performance monitoring: show expected improvements
SELECT 
    'chat_threads' as table_name,
    COUNT(*) as total_rows,
    AVG(thread_messages_count) as avg_messages,
    MAX(thread_messages_count) as max_messages
FROM chat_threads
WHERE is_deleted = FALSE
UNION ALL
SELECT 
    'travel_itineraries' as table_name,
    COUNT(*) as total_rows,
    AVG(destinations_count) as avg_destinations,
    MAX(destinations_count) as max_destinations
FROM travel_itineraries
WHERE is_deleted = FALSE;
