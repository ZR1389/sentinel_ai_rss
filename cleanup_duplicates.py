#!/usr/bin/env python3
"""
Cleanup duplicate alerts caused by old UUID formula that included 'source'.

This script:
1. Identifies duplicates by title similarity and link
2. Keeps the OLDEST record (by published date) for each duplicate group
3. Deletes newer duplicates from both raw_alerts and alerts tables
4. Reports statistics on what was cleaned up
"""

import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import hashlib
from collections import defaultdict

def get_db_connection():
    """Get database connection from environment variable."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)
    return psycopg2.connect(db_url)

def generate_new_uuid(title: str, link: str) -> str:
    """Generate UUID using new formula (title + link only)."""
    content = f"{title}:{link}"
    return hashlib.md5(content.encode('utf-8')).hexdigest()

def find_duplicates_in_raw_alerts(cursor):
    """Find duplicate groups in raw_alerts based on title+link similarity."""
    print("\n🔍 Scanning raw_alerts for duplicates...")
    
    # Find duplicates by exact title+link match
    query = """
    SELECT 
        title,
        link,
        COUNT(*) as count,
        ARRAY_AGG(id ORDER BY published ASC, ingested_at ASC) as ids,
        ARRAY_AGG(uuid ORDER BY published ASC, ingested_at ASC) as uuids,
        ARRAY_AGG(source ORDER BY published ASC, ingested_at ASC) as sources,
        MIN(published) as oldest_published
    FROM raw_alerts
    WHERE title IS NOT NULL 
      AND link IS NOT NULL
      AND title != ''
      AND link != ''
    GROUP BY title, link
    HAVING COUNT(*) > 1
    ORDER BY COUNT(*) DESC
    """
    
    cursor.execute(query)
    duplicates = cursor.fetchall()
    
    return duplicates

def find_duplicates_in_alerts(cursor):
    """Find duplicate groups in alerts based on title+link similarity."""
    print("\n🔍 Scanning alerts for duplicates...")
    
    query = """
    SELECT 
        title,
        link,
        COUNT(*) as count,
        ARRAY_AGG(id ORDER BY published ASC, created_at ASC) as ids,
        ARRAY_AGG(uuid ORDER BY published ASC, created_at ASC) as uuids,
        ARRAY_AGG(source ORDER BY published ASC, created_at ASC) as sources,
        MIN(published) as oldest_published
    FROM alerts
    WHERE title IS NOT NULL 
      AND link IS NOT NULL
      AND title != ''
      AND link != ''
    GROUP BY title, link
    HAVING COUNT(*) > 1
    ORDER BY COUNT(*) DESC
    """
    
    cursor.execute(query)
    duplicates = cursor.fetchall()
    
    return duplicates

def cleanup_table_duplicates(cursor, table_name, duplicates, dry_run=True):
    """Delete duplicate records, keeping the oldest one."""
    total_duplicates = 0
    total_kept = 0
    total_deleted = 0
    
    for dup in duplicates:
        count = dup['count']
        ids = dup['ids']
        uuids = dup['uuids']
        sources = dup['sources']
        title = dup['title'][:80]
        
        # Keep the first ID (oldest), delete the rest
        keep_id = ids[0]
        delete_ids = ids[1:]
        
        total_duplicates += count
        total_kept += 1
        total_deleted += len(delete_ids)
        
        print(f"\n📦 Duplicate group: {count} copies")
        print(f"   Title: {title}...")
        print(f"   Sources: {', '.join(set(sources))}")
        print(f"   ✅ Keep ID {keep_id} (oldest)")
        print(f"   ❌ Delete IDs: {delete_ids}")
        
        if not dry_run:
            # Delete duplicates
            delete_query = f"DELETE FROM {table_name} WHERE id = ANY(%s)"
            cursor.execute(delete_query, (delete_ids,))
            print(f"   🗑️  Deleted {len(delete_ids)} duplicates from {table_name}")
    
    return {
        'total_duplicates': total_duplicates,
        'total_kept': total_kept,
        'total_deleted': total_deleted
    }

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Clean up duplicate alerts')
    parser.add_argument('--execute', action='store_true', 
                       help='Actually delete duplicates (default is dry-run)')
    args = parser.parse_args()
    
    dry_run = not args.execute
    
    if dry_run:
        print("="*70)
        print("🔍 DRY RUN MODE - No changes will be made")
        print("   Run with --execute to actually delete duplicates")
        print("="*70)
    else:
        print("="*70)
        print("⚠️  EXECUTE MODE - Duplicates will be DELETED")
        print("="*70)
        response = input("Are you sure you want to delete duplicates? (yes/no): ")
        if response.lower() != 'yes':
            print("❌ Aborted")
            sys.exit(0)
    
    # Connect to database
    print("\n📡 Connecting to database...")
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Find duplicates in raw_alerts
        raw_duplicates = find_duplicates_in_raw_alerts(cursor)
        print(f"\n📊 Found {len(raw_duplicates)} duplicate groups in raw_alerts")
        
        if raw_duplicates:
            print("\n" + "="*70)
            print("🧹 CLEANING raw_alerts TABLE")
            print("="*70)
            raw_stats = cleanup_table_duplicates(cursor, 'raw_alerts', raw_duplicates, dry_run)
            
            print("\n" + "="*70)
            print("📊 RAW_ALERTS STATISTICS")
            print("="*70)
            print(f"Total duplicate records: {raw_stats['total_duplicates']}")
            print(f"Records to keep: {raw_stats['total_kept']}")
            print(f"Records to delete: {raw_stats['total_deleted']}")
        
        # Find duplicates in alerts
        alert_duplicates = find_duplicates_in_alerts(cursor)
        print(f"\n📊 Found {len(alert_duplicates)} duplicate groups in alerts")
        
        if alert_duplicates:
            print("\n" + "="*70)
            print("🧹 CLEANING alerts TABLE")
            print("="*70)
            alert_stats = cleanup_table_duplicates(cursor, 'alerts', alert_duplicates, dry_run)
            
            print("\n" + "="*70)
            print("📊 ALERTS STATISTICS")
            print("="*70)
            print(f"Total duplicate records: {alert_stats['total_duplicates']}")
            print(f"Records to keep: {alert_stats['total_kept']}")
            print(f"Records to delete: {alert_stats['total_deleted']}")
        
        if not dry_run:
            # Commit changes
            conn.commit()
            print("\n✅ Changes committed to database")
        else:
            print("\n🔍 Dry run complete - no changes made")
            print("   Run with --execute to actually delete duplicates")
        
        # Summary
        print("\n" + "="*70)
        print("🎉 CLEANUP SUMMARY")
        print("="*70)
        
        if raw_duplicates:
            print(f"raw_alerts: Would delete {raw_stats['total_deleted']} duplicates" if dry_run 
                  else f"raw_alerts: Deleted {raw_stats['total_deleted']} duplicates")
        else:
            print("raw_alerts: No duplicates found ✨")
        
        if alert_duplicates:
            print(f"alerts: Would delete {alert_stats['total_deleted']} duplicates" if dry_run 
                  else f"alerts: Deleted {alert_stats['total_deleted']} duplicates")
        else:
            print("alerts: No duplicates found ✨")
        
        total_deleted = (raw_stats.get('total_deleted', 0) if raw_duplicates else 0) + \
                       (alert_stats.get('total_deleted', 0) if alert_duplicates else 0)
        
        if total_deleted > 0:
            print(f"\nTotal records {'would be' if dry_run else ''} deleted: {total_deleted}")
        else:
            print("\n✨ Database is clean - no duplicates found!")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()
        print("\n📡 Database connection closed")

if __name__ == "__main__":
    main()
