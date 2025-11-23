#!/usr/bin/env python3
"""Recalculate saved_searches over-limit flags after plan downgrades.

Logic:
 1. Build per-user plan limit mapping (FREE=0, PRO=3, BUSINESS=10, ENTERPRISE=None(unlimited)).
 2. Rank each saved_search for a user by creation timestamp ascending.
 3. Set is_over_limit=true and alert_enabled=false for rows beyond limit.
 4. Clear is_over_limit for rows within limit (keeps existing alert_enabled state).

Idempotent: Safe to run multiple times; only updates rows where state differs.

Usage:
  DATABASE_URL=postgres://... python scripts/recalc_saved_search_limits.py

Exit codes:
 0 success, non-zero on error.
"""
from __future__ import annotations
import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime

LIMIT_MAP = {
    'FREE': 0,
    'PRO': 3,
    'BUSINESS': 10,
    'ENTERPRISE': None  # unlimited
}

def main():
    dsn = os.getenv('DATABASE_URL') or os.getenv('DATABASE_PUBLIC_URL')
    if not dsn:
        print('ERROR: DATABASE_URL not set', file=sys.stderr)
        return 2
    try:
        conn = psycopg2.connect(dsn)
    except Exception as e:
        print(f'ERROR: could not connect to database: {e}', file=sys.stderr)
        return 3

    sql = """
    WITH limits AS (
        SELECT id AS user_id,
               UPPER(plan) AS plan,
               CASE UPPER(plan)
                 WHEN 'FREE' THEN 0
                 WHEN 'PRO' THEN 3
                 WHEN 'BUSINESS' THEN 10
                 WHEN 'ENTERPRISE' THEN NULL
                 ELSE 0 END AS lim
        FROM users
    ), ranked AS (
        SELECT s.id,
               s.user_id,
               s.created_at,
               ROW_NUMBER() OVER (PARTITION BY s.user_id ORDER BY s.created_at ASC) AS rn,
               l.lim
        FROM saved_searches s
        JOIN limits l ON l.user_id = s.user_id
    )
    UPDATE saved_searches ss
       SET is_over_limit = CASE
                              WHEN r.lim IS NULL THEN FALSE
                              WHEN r.rn > r.lim THEN TRUE
                              ELSE FALSE END,
           alert_enabled = CASE
                              WHEN r.lim IS NOT NULL AND r.rn > r.lim THEN FALSE
                              ELSE ss.alert_enabled END
    FROM ranked r
    WHERE ss.id = r.id
      AND (
            -- only update rows where state differs
            ss.is_over_limit IS DISTINCT FROM (CASE WHEN r.lim IS NULL THEN FALSE WHEN r.rn > r.lim THEN TRUE ELSE FALSE END)
            OR (r.lim IS NOT NULL AND r.rn > r.lim AND ss.alert_enabled IS NOT FALSE)
          );
    """
    try:
        with conn, conn.cursor() as cur:
            cur.execute(sql)
            updated = cur.rowcount
        print(f"Recalc complete: updated rows={updated} at {datetime.utcnow().isoformat()}Z")
        return 0
    except Exception as e:
        print(f'ERROR: recalc failed: {e}', file=sys.stderr)
        return 4
    finally:
        try:
            conn.close()
        except Exception:
            pass

if __name__ == '__main__':
    sys.exit(main())
