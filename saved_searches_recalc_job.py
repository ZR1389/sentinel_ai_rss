"""Periodic job to re-evaluate saved_searches over-limit status.

Intended to be scheduled (cron / Railway) daily or after plan sync events.
Simply imports and runs the recalc script logic (shared function extracted if needed).
"""
from __future__ import annotations
import os
import logging
import subprocess
from datetime import datetime

logger = logging.getLogger('saved_searches_recalc_job')
logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO'))

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), 'scripts', 'recalc_saved_search_limits.py')

def run_job():
    dsn = os.getenv('DATABASE_URL') or os.getenv('DATABASE_PUBLIC_URL')
    if not dsn:
        logger.error('DATABASE_URL not set; aborting recalc job')
        return False
    if not os.path.exists(SCRIPT_PATH):
        logger.error('Recalc script missing at %s', SCRIPT_PATH)
        return False
    try:
        result = subprocess.run(['python3', SCRIPT_PATH], capture_output=True, text=True, check=False)
        if result.returncode == 0:
            logger.info('Saved searches recalc succeeded: %s', result.stdout.strip())
            return True
        logger.error('Recalc failed rc=%s stderr=%s', result.returncode, result.stderr.strip())
        return False
    except Exception as e:
        logger.exception('Recalc job execution error: %s', e)
        return False

if __name__ == '__main__':
    ok = run_job()
    print(f"saved_searches_recalc_job status={'ok' if ok else 'error'} time={datetime.utcnow().isoformat()}Z")
