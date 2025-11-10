#!/usr/bin/env python3
"""
Threat Engine Reprocessor

This script uses the threat_engine.py to fully reprocess existing alerts,
applying all current enrichment logic including HTML cleaning, threat scoring,
and risk analysis. This is more comprehensive than just HTML cleaning.

Usage:
    python scripts/reprocess_via_threat_engine.py [--dry-run] [--days-back=7] [--batch-size=50]
    
Arguments:
    --dry-run: Show what would be changed without making actual updates
    --days-back: Only process alerts from the last N days (default: 7)
    --batch-size: Number of alerts to process per batch (default: 50)
    
Note: This is more resource-intensive as it runs full threat analysis
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta
from typing import List, Dict

# Add parent directory to path to import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_utils
from threat_engine import summarize_single_alert
from rss_processor import _clean_html_content

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/reprocess_threat_engine.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)


def get_alerts_for_reprocessing(days_back: int = 7, batch_size: int = 50, offset: int = 0) -> List[Dict]:
    """
    Fetch alerts to reprocess through threat engine.
    
    Args:
        days_back: Number of days to look back
        batch_size: Maximum number of alerts to return
        offset: Offset for pagination
        
    Returns:
        List of alert dictionaries
    """
    cutoff_date = datetime.now() - timedelta(days=days_back)
    
    query = """
        SELECT id, uuid, title, summary, link, source, published,
               region, country, city, latitude, longitude, category,
               subcategory, created_at
        FROM alerts
        WHERE created_at >= %s
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """
    
    try:
        results = db_utils.fetch_all(query, (cutoff_date, batch_size, offset))
        alerts = []
        
        for row in results:
            alert = {
                'id': row['id'],
                'uuid': row['uuid'],
                'title': row['title'] or '',
                'summary': row['summary'] or '',
                'link': row['link'] or '',
                'source': row['source'] or '',
                'published': row['published'],
                'region': row['region'] or '',
                'country': row['country'] or '',
                'city': row['city'] or '',
                'latitude': float(row['latitude']) if row['latitude'] else None,
                'longitude': float(row['longitude']) if row['longitude'] else None,
                'category': row['category'] or '',
                'subcategory': row['subcategory'] or '',
                'created_at': row['created_at']
            }
            alerts.append(alert)
            
        return alerts
        
    except Exception as e:
        logger.error(f"Failed to fetch alerts for reprocessing: {e}")
        return []


def reprocess_alert_via_threat_engine(alert: Dict, dry_run: bool = False) -> bool:
    """
    Reprocess a single alert through the threat engine.
    
    Args:
        alert: Alert dictionary
        dry_run: If True, don't update database
        
    Returns:
        True if successfully processed and updated
    """
    try:
        # First apply HTML cleaning to the raw content
        original_title = alert.get('title', '')
        original_summary = alert.get('summary', '')
        
        cleaned_title = _clean_html_content(original_title)
        cleaned_summary = _clean_html_content(original_summary)
        
        # Update alert with cleaned content for processing
        alert['title'] = cleaned_title
        alert['summary'] = cleaned_summary
        
        # Run through threat engine for full enrichment
        logger.info(f"Processing alert {alert['id']} through threat engine...")
        enriched_alert = summarize_single_alert(alert.copy())
        
        if not enriched_alert:
            logger.warning(f"Threat engine returned no data for alert {alert['id']}")
            return False
        
        # Prepare update fields with key enrichment data
        update_fields = {
            'title': cleaned_title,
            'summary': cleaned_summary,
            'gpt_summary': enriched_alert.get('gpt_summary', ''),
            'threat_level': enriched_alert.get('threat_level', ''),
            'threat_label': enriched_alert.get('threat_label', ''),
            'threat_type': enriched_alert.get('threat_type', ''),
            'score': enriched_alert.get('score', ''),
            'confidence': enriched_alert.get('confidence', ''),
            'reasoning': enriched_alert.get('reasoning', ''),
            'sentiment': enriched_alert.get('sentiment', ''),
            'forecast': enriched_alert.get('forecast', ''),
            'legal_risk': enriched_alert.get('legal_risk', ''),
            'cyber_ot_risk': enriched_alert.get('cyber_ot_risk', ''),
            'environmental_epidemic_risk': enriched_alert.get('environmental_epidemic_risk', ''),
            'model_used': enriched_alert.get('model_used', ''),
            'updated_at': 'NOW()'
        }
        
        # Show what would be updated
        logger.info(f"Alert {alert['id']} reprocessing results:")
        if original_title != cleaned_title:
            logger.info(f"  Title cleaned: {len(original_title)} → {len(cleaned_title)} chars")
        if original_summary != cleaned_summary:
            logger.info(f"  Summary cleaned: {len(original_summary)} → {len(cleaned_summary)} chars")
        
        logger.info(f"  Threat Level: {enriched_alert.get('threat_level', 'N/A')}")
        logger.info(f"  Threat Label: {enriched_alert.get('threat_label', 'N/A')}")
        logger.info(f"  Model Used: {enriched_alert.get('model_used', 'N/A')}")
        
        if not dry_run:
            # Build dynamic UPDATE query
            set_clauses = []
            values = []
            
            for field, value in update_fields.items():
                if field == 'updated_at':
                    set_clauses.append(f"{field} = NOW()")
                else:
                    set_clauses.append(f"{field} = %s")
                    values.append(value)
            
            values.append(alert['id'])  # WHERE id = %s
            
            update_query = f"""
                UPDATE alerts 
                SET {', '.join(set_clauses)}
                WHERE id = %s
            """
            
            db_utils.execute(update_query, tuple(values))
            logger.info(f"✅ Updated alert {alert['id']} with enriched data")
        else:
            logger.info(f"🔍 [DRY RUN] Would update alert {alert['id']}")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to reprocess alert {alert['id']}: {e}")
        return False


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(description='Reprocess alerts via threat engine')
    parser.add_argument('--dry-run', action='store_true', help='Show changes without applying them')
    parser.add_argument('--batch-size', type=int, default=50, help='Alerts to process per batch')
    parser.add_argument('--days-back', type=int, default=7, help='Days to look back')
    parser.add_argument('--max-alerts', type=int, default=0, help='Maximum total alerts to process (0 = unlimited)')
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("Starting Threat Engine Reprocessing")
    logger.info("=" * 60)
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE UPDATE'}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info(f"Days back: {args.days_back}")
    logger.info(f"Max alerts: {args.max_alerts if args.max_alerts > 0 else 'UNLIMITED'}")
    logger.info("=" * 60)
    
    total_processed = 0
    total_updated = 0
    offset = 0
    
    try:
        while True:
            # Check limits
            if args.max_alerts > 0 and total_processed >= args.max_alerts:
                logger.info(f"Reached maximum alert limit of {args.max_alerts}")
                break
                
            # Fetch next batch
            remaining = args.max_alerts - total_processed if args.max_alerts > 0 else args.batch_size
            batch_size = min(args.batch_size, remaining) if args.max_alerts > 0 else args.batch_size
            
            alerts = get_alerts_for_reprocessing(args.days_back, batch_size, offset)
            
            if not alerts:
                logger.info("No more alerts to process")
                break
                
            logger.info(f"Processing batch of {len(alerts)} alerts (offset: {offset})")
            
            # Process each alert in the batch
            batch_updated = 0
            for alert in alerts:
                total_processed += 1
                
                if reprocess_alert_via_threat_engine(alert, args.dry_run):
                    batch_updated += 1
                    total_updated += 1
            
            logger.info(f"Batch complete: {batch_updated}/{len(alerts)} alerts successfully reprocessed")
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
    logger.info("Threat Engine Reprocessing Complete")
    logger.info("=" * 60)
    logger.info(f"Total alerts processed: {total_processed}")
    logger.info(f"Total alerts updated: {total_updated}")
    logger.info(f"Success rate: {(total_updated/total_processed*100):.1f}%" if total_processed > 0 else "No alerts processed")
    
    if args.dry_run:
        logger.info("\n🔍 This was a DRY RUN - no database changes were made")
        logger.info("Run without --dry-run to apply the changes")
    else:
        logger.info("\n✅ Database has been updated with reprocessed alerts")
        logger.info("Alerts now have current threat analysis and clean HTML content")


if __name__ == "__main__":
    main()
