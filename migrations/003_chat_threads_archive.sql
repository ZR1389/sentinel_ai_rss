-- Migration 003: Chat threads with archiving and per-thread limits
-- Supports dual-limit model: active thread count + per-thread message cap

-- Chat threads table (conversations)
CREATE TABLE IF NOT EXISTS chat_threads (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_uuid UUID UNIQUE DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    investigation_topic TEXT,
    message_count INTEGER DEFAULT 0,
    is_archived BOOLEAN DEFAULT FALSE,
    is_deleted BOOLEAN DEFAULT FALSE,
    archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Thread messages table
CREATE TABLE IF NOT EXISTS chat_messages (
    id SERIAL PRIMARY KEY,
    thread_id INTEGER NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_threads_user ON chat_threads(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_threads_active ON chat_threads(user_id, is_archived, is_deleted, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_threads_uuid ON chat_threads(thread_uuid);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON chat_messages(thread_id, created_at);

-- View for active thread count (excludes archived and deleted)
CREATE OR REPLACE VIEW user_active_threads AS
SELECT 
    user_id, 
    COUNT(*) as active_count,
    COUNT(*) FILTER (WHERE is_archived = TRUE) as archived_count
FROM chat_threads
WHERE is_deleted = FALSE
GROUP BY user_id;

-- Trigger to update thread message_count and updated_at
CREATE OR REPLACE FUNCTION update_thread_stats()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE chat_threads
    SET message_count = (
        SELECT COUNT(*) FROM chat_messages WHERE thread_id = NEW.thread_id
    ),
    updated_at = NOW()
    WHERE id = NEW.thread_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER thread_message_added
AFTER INSERT ON chat_messages
FOR EACH ROW
EXECUTE FUNCTION update_thread_stats();

-- Function to check active thread limit
CREATE OR REPLACE FUNCTION check_thread_limit(p_user_id INTEGER, p_plan TEXT)
RETURNS BOOLEAN AS $$
DECLARE
    active_count INTEGER;
    thread_limit INTEGER;
BEGIN
    -- Get active thread count (excludes archived and deleted)
    SELECT COUNT(*) INTO active_count
    FROM chat_threads
    WHERE user_id = p_user_id 
      AND is_archived = FALSE 
      AND is_deleted = FALSE;
    
    -- Determine limit based on plan
    thread_limit := CASE p_plan
        WHEN 'FREE' THEN 5
        WHEN 'PRO' THEN 50
        WHEN 'BUSINESS' THEN 100
        WHEN 'ENTERPRISE' THEN NULL  -- unlimited
        ELSE 5  -- default to FREE
    END;
    
    -- NULL means unlimited
    IF thread_limit IS NULL THEN
        RETURN TRUE;
    END IF;
    
    RETURN active_count < thread_limit;
END;
$$ LANGUAGE plpgsql;

-- Function to check per-thread message limit
CREATE OR REPLACE FUNCTION check_thread_message_limit(p_thread_id INTEGER, p_plan TEXT)
RETURNS BOOLEAN AS $$
DECLARE
    msg_count INTEGER;
    msg_limit INTEGER;
BEGIN
    -- Get current message count for thread
    SELECT COUNT(*) INTO msg_count
    FROM chat_messages
    WHERE thread_id = p_thread_id;
    
    -- Determine limit based on plan
    msg_limit := CASE p_plan
        WHEN 'FREE' THEN 3
        WHEN 'PRO' THEN 50
        WHEN 'BUSINESS' THEN 100
        WHEN 'ENTERPRISE' THEN NULL  -- unlimited
        ELSE 3  -- default to FREE
    END;
    
    -- NULL means unlimited
    IF msg_limit IS NULL THEN
        RETURN TRUE;
    END IF;
    
    RETURN msg_count < msg_limit;
END;
$$ LANGUAGE plpgsql;

-- Function to get monthly message count (global safety valve)
CREATE OR REPLACE FUNCTION get_monthly_message_count(p_user_id INTEGER)
RETURNS INTEGER AS $$
DECLARE
    msg_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO msg_count
    FROM chat_messages cm
    JOIN chat_threads ct ON cm.thread_id = ct.id
    WHERE ct.user_id = p_user_id
      AND cm.created_at >= date_trunc('month', CURRENT_DATE);
    
    RETURN COALESCE(msg_count, 0);
END;
$$ LANGUAGE plpgsql;

-- Comments for documentation
COMMENT ON TABLE chat_threads IS 'User conversation threads with archive support';
COMMENT ON COLUMN chat_threads.is_archived IS 'Archived threads do not count against active thread limit';
COMMENT ON COLUMN chat_threads.message_count IS 'Cached count of messages in thread, updated by trigger';
COMMENT ON TABLE chat_messages IS 'Individual messages within conversation threads';
COMMENT ON FUNCTION check_thread_limit IS 'Validates active thread count against plan limit (excludes archived)';
COMMENT ON FUNCTION check_thread_message_limit IS 'Validates per-thread message count against plan limit';
COMMENT ON FUNCTION get_monthly_message_count IS 'Returns total messages sent this month (safety valve)';
