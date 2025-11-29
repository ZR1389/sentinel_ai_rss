-- Migration: Add PDF export tracking to user_usage table
-- Date: 2025-11-25
-- Description: Track monthly PDF exports for plan enforcement (Free=1, Pro=10, Business/Enterprise=unlimited)

-- Add pdf_exports_used column to user_usage table
ALTER TABLE user_usage 
ADD COLUMN IF NOT EXISTS pdf_exports_used INTEGER DEFAULT 0 NOT NULL;

-- Add comment for documentation
COMMENT ON COLUMN user_usage.pdf_exports_used IS 'Number of PDF exports used in current monthly period';

-- Create pdf_exports table for tracking generated PDFs and expiry
CREATE TABLE IF NOT EXISTS pdf_exports (
    id UUID PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    template VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW() NOT NULL,
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    downloaded_at TIMESTAMP WITHOUT TIME ZONE
);

-- Add indexes for performance
CREATE INDEX IF NOT EXISTS idx_pdf_exports_user_id ON pdf_exports(user_id);
CREATE INDEX IF NOT EXISTS idx_pdf_exports_expires_at ON pdf_exports(expires_at);
CREATE INDEX IF NOT EXISTS idx_pdf_exports_created_at ON pdf_exports(created_at DESC);

-- Add comment for documentation
COMMENT ON TABLE pdf_exports IS 'Tracks generated PDF exports with expiry and download metadata';

-- Verify columns were added
SELECT column_name, data_type, column_default 
FROM information_schema.columns 
WHERE table_name = 'user_usage' 
AND column_name = 'pdf_exports_used';

SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_name = 'pdf_exports'
ORDER BY ordinal_position;
