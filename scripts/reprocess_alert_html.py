#!/usr/bin/env python3
"""
Reprocess Alert HTML Cleaning Script

This script applies the new HTML cleaning logic to existing alerts in the database.
It updates the title and summary fields to remove HTML tags and formatting issues
that were causing display problems in the frontend map.

Usage:
    python scripts/reprocess_alert_html.py [--dry-run] [--batch-size=100] [--days-back=30]
    
Arguments:
    --dry-run: Show what would be changed without making actual updates
    --batch-size: Number of alerts to process per batch (default: 100)
    --days-back: Only process alerts from the last N days (default: 30, 0 = all)
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta
from typing import List, Tuple

# Add parent directory to path to import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_utils
from rss_processor import _clean_html_content

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/reprocess_html_cleaning.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)


def get_alerts_to_process(days_back: int = 30, batch_size: int = 100, offset: int = 0) -> List[dict]:
    """
    Fetch alerts that may need HTML cleaning.
    
    Args:
        days_back: Number of days to look back (0 = all alerts)
        batch_size: Maximum number of alerts to return
        offset: Offset for pagination
        
    Returns:
        List of alert dictionaries with id, title, summary, created_at
    """
    # Build WHERE clause for date filtering
    where_clause = ""
    params = []
    
    if days_back > 0:
        cutoff_date = datetime.now() - timedelta(days=days_back)
        where_clause = "WHERE created_at >= %s"
        params.append(cutoff_date)
    
    query = f"""
        SELECT id, title, summary, created_at
        FROM alerts
        {where_clause}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """
    params.extend([batch_size, offset])
    
    try:
        results = db_utils.fetch_all(query, tuple(params))
        return [
            {
                'id': row['id'],
                'title': row['title'] or '',
                'summary': row['summary'] or '',
                'created_at': row['created_at']
            }
            for row in results
        ]
    except Exception as e:
        logger.error(f"Failed to fetch alerts: {e}")
        return []


def needs_html_cleaning(text: str) -> bool:
    """
    Check if text contains HTML that should be cleaned.
    
    Args:
        text: Text to check
        
    Returns:
        True if text contains HTML tags or entities that need cleaning
    """
    if not text:
        return False
    
    import re
    
    # Check for HTML tags
    if re.search(r'<[^>]+>', text):
        return True
        
    # Check for HTML entities
    if re.search(r'&[a-zA-Z0-9#]+;', text):
        return True
        
    # Check for common RSS patterns
    patterns = [
        r'The post.*?appeared first on.*?\.',
        r'\[&#?8230;?\]',  # [...] truncation markers
        r'\[…\]',
        r'\[\.\.\.\]',
        r'Continue reading.*',
        r'Read more.*',
        r'Full article.*',
    ]
    
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
            return True
            
    return False


def process_alert_batch(alerts: List[dict], dry_run: bool = False) -> Tuple[int, int]:
    """
    Process a batch of alerts, cleaning their HTML content.
    
    Args:
        alerts: List of alert dictionaries
        dry_run: If True, don't actually update the database
        
    Returns:
        Tuple of (processed_count, updated_count)
    """
    processed = 0
    updated = 0
    
    for alert in alerts:
        processed += 1
        alert_id = alert['id']
        original_title = alert['title']
        original_summary = alert['summary']
        
        # Check if either field needs cleaning
        title_needs_cleaning = needs_html_cleaning(original_title)
        summary_needs_cleaning = needs_html_cleaning(original_summary)
        
        if not (title_needs_cleaning or summary_needs_cleaning):
            continue
            
        # Clean the content
        cleaned_title = _clean_html_content(original_title) if title_needs_cleaning else original_title
        cleaned_summary = _clean_html_content(original_summary) if summary_needs_cleaning else original_summary
        
        # Show what would be changed
        if title_needs_cleaning:
            logger.info(f"Alert {alert_id} - Title would be cleaned:")
            logger.info(f"  Before: {original_title[:100]}{'...' if len(original_title) > 100 else ''}")
            logger.info(f"  After:  {cleaned_title[:100]}{'...' if len(cleaned_title) > 100 else ''}")
            
        if summary_needs_cleaning:
            logger.info(f"Alert {alert_id} - Summary would be cleaned:")
            logger.info(f"  Before: {original_summary[:100]}{'...' if len(original_summary) > 100 else ''}")
            logger.info(f"  After:  {cleaned_summary[:100]}{'...' if len(cleaned_summary) > 100 else ''}")
        
        # Update database if not dry run
        if not dry_run:
            try:
                update_query = """
                    UPDATE alerts 
                    SET title = %s, summary = %s, updated_at = NOW()
                    WHERE id = %s
                """
                db_utils.execute(update_query, (cleaned_title, cleaned_summary, alert_id))
                logger.info(f"✅ Updated alert {alert_id}")
                updated += 1
            except Exception as e:
                logger.error(f"❌ Failed to update alert {alert_id}: {e}")
        else:
            logger.info(f"🔍 [DRY RUN] Would update alert {alert_id}")
            updated += 1
    
    return processed, updated


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(description='Reprocess alert HTML content')
    parser.add_argument('--dry-run', action='store_true', help='Show changes without applying them')
    parser.add_argument('--batch-size', type=int, default=100, help='Alerts to process per batch')
    parser.add_argument('--days-back', type=int, default=30, help='Days to look back (0 = all alerts)')
    parser.add_argument('--max-alerts', type=int, default=0, help='Maximum total alerts to process (0 = unlimited)')
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("Starting Alert HTML Cleaning Reprocessing")
    logger.info("=" * 60)
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE UPDATE'}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Days back: {args.days_back if args.days_back > 0 else 'ALL'}")
    logger.info(f"Max alerts: {args.max_alerts if args.max_alerts > 0 else 'UNLIMITED'}")
    logger.info("=" * 60)
    
    total_processed = 0
    total_updated = 0
    offset = 0
    
    try:
        while True:
            # Check if we've hit the max alerts limit
            if args.max_alerts > 0 and total_processed >= args.max_alerts:
                logger.info(f"Reached maximum alert limit of {args.max_alerts}")
                break
                
            # Fetch next batch
            remaining = args.max_alerts - total_processed if args.max_alerts > 0 else args.batch_size
            batch_size = min(args.batch_size, remaining) if args.max_alerts > 0 else args.batch_size
            
            alerts = get_alerts_to_process(args.days_back, batch_size, offset)
            
            if not alerts:
                logger.info("No more alerts to process")
                break
                
            logger.info(f"Processing batch of {len(alerts)} alerts (offset: {offset})")
            
            # Process the batch
            batch_processed, batch_updated = process_alert_batch(alerts, args.dry_run)
            
            total_processed += batch_processed
            total_updated += batch_updated
            
            logger.info(f"Batch complete: {batch_updated}/{batch_processed} alerts needed cleaning")
            logger.info(f"Running totals: {total_updated}/{total_processed} alerts processed")
            
            # Move to next batch
            offset += len(alerts)
            
            # If we got fewer alerts than requested, we're done
            if len(alerts) < batch_size:
                logger.info("Reached end of alerts")
                break
                
    except KeyboardInterrupt:
        logger.info("Process interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error during processing: {e}")
        sys.exit(1)
    
    logger.info("=" * 60)
    logger.info("HTML Cleaning Reprocessing Complete")
    logger.info("=" * 60)
    logger.info(f"Total alerts processed: {total_processed}")
    logger.info(f"Total alerts updated: {total_updated}")
    logger.info(f"Update rate: {(total_updated/total_processed*100):.1f}%" if total_processed > 0 else "No alerts processed")
    
    if args.dry_run:
        logger.info("\n🔍 This was a DRY RUN - no database changes were made")
        logger.info("Run without --dry-run to apply the changes")
    else:
        logger.info("\n✅ Database has been updated with cleaned content")
        logger.info("Frontend map should now display clean, readable text")


if __name__ == "__main__":
    main()
