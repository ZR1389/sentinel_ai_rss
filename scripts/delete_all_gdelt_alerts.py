#!/usr/bin/env python3
"""
scripts/delete_all_gdelt_alerts.py

Delete ALL GDELT alerts from the alerts table.

Why: Existing GDELT alerts lack rich metadata (goldstein, num_mentions, etc.) 
needed for filtering. They only have simple tags like ['gdelt', 'quad_3', '110'].
The new filtering system will only work on future GDELT events.
"""
import os
import sys
import argparse
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from dotenv import load_dotenv

# Load production environment
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
production_env = os.path.join(project_root, '.env.production')

if not os.path.exists(production_env):
    print(f"ERROR: {production_env} not found")
    sys.exit(1)

load_dotenv(production_env, override=True)

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL or not DATABASE_URL.startswith('postgresql://'):
    print(f"ERROR: Invalid DATABASE_URL in .env.production")
    sys.exit(1)

print(f"✓ Connected to PostgreSQL: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'database'}")
print()


def delete_all_gdelt_alerts(dry_run=True):
    """Delete all GDELT alerts from alerts table"""
    
    print(f"{'=' * 70}")
    print(f"Delete All GDELT Alerts {'(DRY RUN - Safe Mode)' if dry_run else '(LIVE MODE)'}")
    print(f"{'=' * 70}")
    print("\n⚠️  WARNING: This will DELETE ALL GDELT alerts from alerts table")
    print("   Reason: Existing alerts lack metadata needed for selective filtering")
    print("   New alerts will be properly filtered by the aggressive filter system\n")
    
    start_time = datetime.now()
    print(f"Started: {start_time}\n")
    
    # Connect and count
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM alerts WHERE LOWER(source) = 'gdelt'")
    total_count = cur.fetchone()[0]
    
    print(f"Total GDELT alerts in database: {total_count:,}\n")
    
    if total_count == 0:
        print("No GDELT alerts found. Nothing to do.")
        cur.close()
        conn.close()
        return 0
    
    print(f"{'=' * 70}\n")
    
    if dry_run:
        print(f"Would delete all {total_count:,} GDELT alerts")
        deleted_count = 0
    else:
        print(f"Deleting {total_count:,} GDELT alerts...")
        cur.execute("DELETE FROM alerts WHERE LOWER(source) = 'gdelt'")
        deleted_count = cur.rowcount
        conn.commit()
        print(f"✓ Deleted {deleted_count:,} alerts")
    
    cur.close()
    conn.close()
    
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    print(f"\n{'=' * 70}")
    print("Summary")
    print(f"{'=' * 70}")
    print(f"Total GDELT alerts: {total_count:,}")
    print(f"Deleted: {deleted_count if not dry_run else total_count:,}")
    print(f"Duration: {duration:.1f} seconds")
    print(f"Finished: {end_time}")
    
    if dry_run:
        print(f"\n{'⚠' * 35}")
        print(f"⚠  THIS WAS A DRY RUN - NO DATA WAS DELETED  ⚠")
        print(f"{'⚠' * 35}\n")
        print("To execute deletion for real, run:")
        print("  python scripts/delete_all_gdelt_alerts.py --live")
        print("\nOr type 'DELETE' to confirm:")
        confirmation = input("> ").strip()
        if confirmation == 'DELETE':
            print("\nRunning live deletion...")
            return delete_all_gdelt_alerts(dry_run=False)
    else:
        print("\n✅ Cleanup completed successfully!")
        print("\nNext steps:")
        print("1. Run VACUUM to reclaim disk space:")
        print("   python vacuum_only.py")
        print("\n2. Deploy new filtering code to prevent future noise:")
        print("   git add . && git commit -m 'GDELT filtering' && git push")
        print("\n3. Monitor filter effectiveness:")
        print("   Check /admin/gdelt/filter-stats endpoint")
    
    return deleted_count if not dry_run else 0


def main():
    parser = argparse.ArgumentParser(
        description='Delete all GDELT alerts from alerts table'
    )
    parser.add_argument(
        '--live',
        action='store_true',
        help='Execute deletion (default is dry-run)'
    )
    
    args = parser.parse_args()
    
    try:
        delete_all_gdelt_alerts(dry_run=not args.live)
    except KeyboardInterrupt:
        print("\n\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
