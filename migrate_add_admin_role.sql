-- Migration: Add admin role to users table
-- Adds is_admin column for admin panel access control
-- Idempotent: safe to re-run

-- Add is_admin column (default false)
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;

-- Create index for admin lookups
CREATE INDEX IF NOT EXISTS idx_users_is_admin ON users(is_admin) WHERE is_admin = true;

-- Set specific admin users (update these emails as needed)
-- UPDATE users SET is_admin = true WHERE email IN ('admin@zikarisk.com', 'ops@zikarisk.com');

COMMENT ON COLUMN users.is_admin IS 'Admin role flag for admin panel access';
