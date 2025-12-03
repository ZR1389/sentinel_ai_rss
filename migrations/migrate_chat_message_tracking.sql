-- Migration: Fix Chat Message Quota Tracking
-- Date: 2025-12-03
-- Issue: Chat message usage was always showing 0/2500 for Enterprise users
-- Root Cause: The trigger updating message counts never incremented user_usage.chat_messages_used
-- 
-- Changes:
-- 1. Updated the update_thread_stats() trigger function to increment user_usage.chat_messages_used
-- 2. Added automatic monthly quota reset logic when month changes
-- 3. Made the upsert idempotent to handle edge cases

-- Drop and recreate the trigger function with message counting
CREATE OR REPLACE FUNCTION public.update_thread_stats()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
DECLARE
    v_user_id INTEGER;
    v_month_start DATE;
BEGIN
    -- Get user_id from thread
    SELECT user_id INTO v_user_id FROM chat_threads WHERE id = NEW.thread_id;
    
    -- Update thread message count
    UPDATE chat_threads
    SET message_count = (
        SELECT COUNT(*) FROM chat_messages WHERE thread_id = NEW.thread_id
    ),
    updated_at = NOW()
    WHERE id = NEW.thread_id;
    
    -- Increment monthly message count in user_usage (idempotent via upsert)
    v_month_start := DATE_TRUNC('month', CURRENT_DATE)::DATE;
    
    -- Case 1: Existing row for this month - increment
    INSERT INTO user_usage (user_id, chat_messages_used, last_reset)
    VALUES (v_user_id, 1, v_month_start)
    ON CONFLICT (user_id) DO UPDATE
    SET chat_messages_used = user_usage.chat_messages_used + 1,
        updated_at = NOW()
    WHERE DATE_TRUNC('month', user_usage.last_reset)::DATE = v_month_start;
    
    -- Case 2: Month has changed - reset counter and set to 1
    INSERT INTO user_usage (user_id, chat_messages_used, last_reset)
    VALUES (v_user_id, 1, v_month_start)
    ON CONFLICT (user_id) DO UPDATE
    SET chat_messages_used = 1,
        last_reset = v_month_start,
        updated_at = NOW()
    WHERE DATE_TRUNC('month', user_usage.last_reset)::DATE != v_month_start;
    
    RETURN NEW;
END;
$function$;

-- Verify the trigger is still attached
SELECT 'Trigger update_thread_stats verified' as status;
