#!/usr/bin/env python3
"""
vacuum_only.py
Standalone script for database vacuum operations in production.

Enhancements:
- Loads `.env.production` (override) to ensure `DATABASE_URL` is available when invoked via cron.
- Supports `--full` flag for a heavier `VACUUM FULL` (table-level rewrite) when needed.
- Default mode performs lightweight `VACUUM ANALYZE` via `retention_worker.perform_vacuum()`.

Usage:
  python vacuum_only.py            # VACUUM ANALYZE alerts/raw_alerts/users
  python vacuum_only.py --full     # VACUUM FULL alerts/raw_alerts (longer locks)
"""

import os
import sys
import argparse
from dotenv import load_dotenv

def _load_env():
    # Prefer production env; fall back to generic .env if missing
    if os.path.exists('.env.production'):
        load_dotenv('.env.production', override=True)
    else:
        load_dotenv('.env', override=False)

def _vacuum_full():
    from db_utils import _get_db_connection  # uses DATABASE_URL
    import logging
    logger = logging.getLogger("vacuum_full")
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL missing; cannot run VACUUM FULL")
        raise SystemExit(2)
    logger.info("Starting VACUUM FULL on alerts/raw_alerts")
    try:
        with _get_db_connection() as conn:
            conn.set_session(autocommit=True)
            with conn.cursor() as cur:
                cur.execute("VACUUM FULL alerts")
                cur.execute("VACUUM FULL raw_alerts")
        logger.info("VACUUM FULL completed successfully")
    except Exception as e:
        logger.warning("VACUUM FULL failed", extra={"error": str(e)})
        raise

def main():
    _load_env()
    parser = argparse.ArgumentParser(description="Run database vacuum maintenance")
    parser.add_argument("--full", action="store_true", help="Perform VACUUM FULL (slower, locks tables)")
    args = parser.parse_args()

    if args.full:
        _vacuum_full()
    else:
        from retention_worker import perform_vacuum
        perform_vacuum()

if __name__ == "__main__":
    main()
