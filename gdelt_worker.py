#!/usr/bin/env python3
"""
GDELT Background Worker - Continuous enrichment processor
Runs as a separate Railway service, processes backlog continuously
"""
import os
import time
import logging
from railway_cron import run_gdelt_enrich_once

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gdelt_worker")

BATCH_INTERVAL = int(os.getenv("GDELT_WORKER_INTERVAL", "60"))  # 1 minute between batches

def main():
    logger.info("🚀 GDELT Worker started - processing enrichment backlog")
    
    while True:
        try:
            logger.info("Processing GDELT batch...")
            success = run_gdelt_enrich_once()
            
            if success:
                logger.info(f"✅ Batch complete - waiting {BATCH_INTERVAL}s")
            else:
                logger.warning(f"⚠️  Batch failed - waiting {BATCH_INTERVAL}s")
                
        except Exception as e:
            logger.error(f"❌ Worker error: {e}")
            
        time.sleep(BATCH_INTERVAL)

if __name__ == "__main__":
    main()
