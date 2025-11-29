#!/usr/bin/env python3
"""
Populate embeddings for existing alerts in batches.
This is a one-time migration script to add vector embeddings to existing data.
"""

import sys
import os
import logging
from typing import Optional

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from vector_dedup import VectorDeduplicator
from risk_shared import embedding_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def populate_embeddings(
    batch_size: int = 10, 
    max_alerts: int = 500,
    dry_run: bool = False
) -> int:
    """
    Populate embeddings for existing alerts.
    
    Args:
        batch_size: Number of alerts to process per batch (smaller to respect quotas)
        max_alerts: Maximum alerts to process in this run
        dry_run: If True, only simulate without making changes
        
    Returns:
        Number of embeddings successfully created
    """
    logger.info(f"Starting embedding population (batch_size={batch_size}, max_alerts={max_alerts}, dry_run={dry_run})")
    
    # Initialize vector deduplicator
    vector_dedup = VectorDeduplicator(similarity_threshold=0.92)
    
    if dry_run:
        logger.info("DRY RUN MODE - No actual changes will be made")
        # For dry run, just count what would be processed
        from db_utils import fetch_all
        query = """
            SELECT COUNT(*) as count
            FROM alerts 
            WHERE embedding_json IS NULL
            LIMIT %s
        """
        result = fetch_all(query, (max_alerts,))
        count = result[0]["count"] if result else 0
        logger.info(f"Would process {count} alerts")
        return count
    
    # Check quota status before starting
    status = embedding_manager.get_quota_status()
    logger.info(f"Quota status: {status['daily_tokens']}/{status['token_limit']} tokens used, "
                f"{status['tokens_remaining']} remaining")
    
    if status["tokens_remaining"] < 1000:
        logger.error("Insufficient embedding quota remaining. Please wait for reset or increase limit.")
        return 0
    
    # Get OpenAI client (optional - will use fallback if not available)
    openai_client = None
    try:
        from openai import OpenAI
        from core.config import CONFIG
        api_key = CONFIG.llm.openai_api_key
        if api_key:
            openai_client = OpenAI(api_key=api_key)
            logger.info("Using OpenAI client for embeddings")
        else:
            logger.info("No OpenAI API key found, will use fallback embeddings")
    except Exception as e:
        logger.warning(f"OpenAI client initialization failed: {e}")
    
    # Run batch population
    success_count = vector_dedup.populate_embeddings_batch(
        openai_client=openai_client,
        batch_size=batch_size,
        max_alerts=max_alerts
    )
    
    # Report final quota status
    final_status = embedding_manager.get_quota_status()
    logger.info(f"Final quota status: {final_status['daily_tokens']}/{final_status['token_limit']} tokens used")
    
    return success_count

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Populate embeddings for existing alerts")
    parser.add_argument("--batch-size", type=int, default=10, help="Batch size for processing")
    parser.add_argument("--max-alerts", type=int, default=100, help="Maximum alerts to process")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without making changes")
    
    args = parser.parse_args()
    
    try:
        result = populate_embeddings(
            batch_size=args.batch_size,
            max_alerts=args.max_alerts,
            dry_run=args.dry_run
        )
        print(f"Successfully processed {result} alerts")
    except Exception as e:
        logger.error(f"Script failed: {e}")
        sys.exit(1)
