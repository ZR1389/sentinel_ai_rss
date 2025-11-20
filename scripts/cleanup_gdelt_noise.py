#!/usr/bin/env python3
"""
scripts/cleanup_gdelt_noise.py

Remove existing GDELT alerts that don't pass the new aggressive filters.
Safe to run - includes dry-run mode and batch processing.
"""
import os
import sys
import time
from datetime import datetime
from typing import Dict, Any, Tuple

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from gdelt_filters import should_ingest_gdelt_event

# Load production environment for database access
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
production_env = os.path.join(project_root, '.env.production')

if not os.path.exists(production_env):
    print(f"ERROR: {production_env} not found")
    sys.exit(1)

# Override any existing environment with production values
load_dotenv(production_env, override=True)

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set in .env.production")
    sys.exit(1)

# Validate it's a PostgreSQL URL
if not DATABASE_URL.startswith('postgresql://'):
    print(f"ERROR: DATABASE_URL must be PostgreSQL, got: {DATABASE_URL[:30]}...")
    print("This script requires .env.production with PostgreSQL connection")
    sys.exit(1)

print(f"✓ Connected to PostgreSQL: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'database'}")
print()


def get_connection():
    """Get database connection"""
    return psycopg2.connect(DATABASE_URL)


def fetch_gdelt_alerts(conn, batch_size=1000, offset=0):
    """Fetch GDELT alerts from alerts table in batches"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                uuid,
                latitude,
                longitude,
                score,
                tags
            FROM alerts
            WHERE LOWER(source) = 'gdelt'
            ORDER BY published DESC
            LIMIT %s OFFSET %s
        """, (batch_size, offset))
        return cur.fetchall()


def extract_gdelt_metadata(alert: Dict[str, Any]) -> Dict[str, Any]:
    """Extract GDELT-specific metadata from alert tags"""
    import json
    
    tags = alert.get('tags')
    
    # Handle different tag formats
    # Tags can be: string (JSON), list of dicts [{...}], or dict {...}
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except:
            tags = []
    
    # If tags is a list, get first element (GDELT stores as [{...}])
    if isinstance(tags, list) and len(tags) > 0:
        tags = tags[0] if isinstance(tags[0], dict) else {}
    elif not isinstance(tags, dict):
        tags = {}
    
    # Extract GDELT metadata from tags (stored during enrichment)
    return {
        'global_event_id': tags.get('event_id'),
        'action_lat': alert.get('latitude'),
        'action_long': alert.get('longitude'),
        'goldstein': tags.get('goldstein', 0),
        'num_mentions': tags.get('num_mentions', 0),
        'avg_tone': tags.get('avg_tone', 0),
        'event_code': tags.get('event_code', ''),
        'quad_class': tags.get('quad_class', 0),
        'sql_date': None,  # Not critical for filtering
    }


def cleanup_gdelt_alerts(dry_run=True, batch_size=1000):
    """
    Remove GDELT alerts that don't pass new filters.
    
    NOTE: Existing GDELT alerts in the `alerts` table lack rich metadata
    (goldstein, num_mentions, etc.) needed for filtering. They only have
    simple string tags like ['gdelt', 'quad_3', '110'].
    
    Since we can't properly filter them, this script will DELETE ALL GDELT alerts
    from the alerts table. New alerts will be properly filtered going forward.
    
    Args:
        dry_run: If True, only simulate deletion (safe mode)
        batch_size: Number of alerts to process per batch
    """
    
    print(f"\n{'=' * 70}")
    print(f"GDELT Noise Cleanup {'(DRY RUN - Safe Mode)' if dry_run else '(LIVE MODE)'}")
    print(f"{'=' * 70}")
    print("\n⚠️  WARNING: Existing GDELT alerts lack metadata for filtering")
    print("   This script will DELETE ALL GDELT alerts from alerts table.")
    print("   New alerts will be properly filtered going forward.\n")
    print(f"Started: {datetime.now().isoformat()}")
    
    conn = get_connection()
    
    # First, count total GDELT alerts
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM alerts WHERE LOWER(source) = 'gdelt'")
        total_gdelt = cur.fetchone()[0]
    
    print(f"\nTotal GDELT alerts in database: {total_gdelt:,}")
    
    if total_gdelt == 0:
        print("No GDELT alerts found. Nothing to clean up.")
        conn.close()
        return 0, 0
    
    # Process in batches
    offset = 0
    total_processed = 0
    total_to_delete = 0
    total_kept = 0
    uuids_to_delete = []
    batch_num = 0
    
    print(f"Processing in batches of {batch_size}...")
    print(f"Filter configuration:")
    from gdelt_filters import get_filter_stats
    config = get_filter_stats()
    for key, value in config.items():
        print(f"  {key}: {value}")
    
    print(f"\n{'=' * 70}")
    
    while True:
        # Fetch batch
        alerts = fetch_gdelt_alerts(conn, batch_size=batch_size, offset=offset)
        
        if not alerts:
            break
        
        batch_num += 1
        print(f"\nBatch {batch_num}: Processing {len(alerts)} alerts (offset {offset})...")
        
        batch_delete_count = 0
        batch_keep_count = 0
        
        for alert in alerts:
            total_processed += 1
            
            # Convert to GDELT event format for filter
            event = extract_gdelt_metadata(alert)
            
            # Check against filters
            if should_ingest_gdelt_event(event, stage="enrichment"):
                total_kept += 1
                batch_keep_count += 1
            else:
                total_to_delete += 1
                batch_delete_count += 1
                uuids_to_delete.append(alert['uuid'])
        
        print(f"  Keep: {batch_keep_count}, Delete: {batch_delete_count}")
        
        # Execute batch deletion if we have enough or this is the last batch
        if len(uuids_to_delete) >= batch_size or len(alerts) < batch_size:
            if uuids_to_delete:
                if not dry_run:
                    with conn.cursor() as cur:
                        cur.execute("""
                            DELETE FROM alerts 
                            WHERE uuid = ANY(%s) AND LOWER(source) = 'gdelt'
                        """, (uuids_to_delete,))
                        deleted = cur.rowcount
                        conn.commit()
                        print(f"  → Deleted {deleted} alerts from database")
                else:
                    print(f"  → Would delete {len(uuids_to_delete)} alerts")
                
                uuids_to_delete = []
        
        offset += batch_size
        
        # Progress indicator
        progress = (total_processed / total_gdelt) * 100
        print(f"  Progress: {total_processed:,}/{total_gdelt:,} ({progress:.1f}%)")
        
        time.sleep(0.05)  # Small delay to avoid overwhelming DB
    
    # Final batch if any remaining
    if uuids_to_delete and not dry_run:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM alerts 
                WHERE uuid = ANY(%s) AND LOWER(source) = 'gdelt'
            """, (uuids_to_delete,))
            deleted = cur.rowcount
            conn.commit()
            print(f"\nFinal batch: Deleted {deleted} alerts")
    
    conn.close()
    
    # Summary
    print(f"\n{'=' * 70}")
    print("Cleanup Summary")
    print(f"{'=' * 70}")
    print(f"Total GDELT alerts processed: {total_processed:,}")
    print(f"Kept (passed filters): {total_kept:,} ({total_kept/total_processed*100:.1f}%)")
    print(f"Deleted (failed filters): {total_to_delete:,} ({total_to_delete/total_processed*100:.1f}%)")
    print(f"Finished: {datetime.now().isoformat()}")
    
    if dry_run:
        print(f"\n{'⚠' * 35}")
        print("⚠  THIS WAS A DRY RUN - NO DATA WAS DELETED  ⚠")
        print(f"{'⚠' * 35}")
        print("\nTo execute cleanup for real, run:")
        print("  python scripts/cleanup_gdelt_noise.py --live")
    else:
        print(f"\n✓ Cleanup executed successfully")
        print("\nRecommendations:")
        print("  1. Check /health endpoint to verify alert counts")
        print("  2. Check /api/map-alerts/aggregates for updated map data")
        print("  3. Consider running VACUUM on alerts table:")
        print("     python vacuum_only.py")
    
    return total_to_delete, total_kept


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Clean up GDELT alerts that don\'t pass new filters'
    )
    parser.add_argument(
        '--live',
        action='store_true',
        help='Execute cleanup (default is dry-run)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=1000,
        help='Batch size for processing (default: 1000)'
    )
    
    args = parser.parse_args()
    
    if args.live:
        print("\n" + "=" * 70)
        print("⚠  WARNING: LIVE MODE - THIS WILL DELETE DATA  ⚠")
        print("=" * 70)
        confirm = input("\nType 'DELETE' to confirm permanent deletion: ")
        if confirm.strip() != 'DELETE':
            print("\nAborted.")
            sys.exit(0)
        print("\nProceeding with deletion...\n")
    
    try:
        deleted, kept = cleanup_gdelt_alerts(
            dry_run=not args.live,
            batch_size=args.batch_size
        )
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
