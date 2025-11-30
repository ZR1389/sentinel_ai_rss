#!/usr/bin/env python3
"""
Cleanup alerts with impossible city/country combinations.

Examples:
- Rio De Janeiro, United States → Should be Brazil
- Paris, United States → Could be France or Paris,Texas (ambiguous)
- Beijing, United Kingdom → Should be China

This script:
1. Identifies alerts with invalid city/country combinations
2. Attempts to fix them using CITY_TO_COUNTRY mapping
3. Deletes alerts that can't be fixed
"""

import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

def get_db_connection():
    """Get database connection from environment variable."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)
    return psycopg2.connect(db_url)

def get_city_to_country_mapping():
    """Import CITY_TO_COUNTRY mapping."""
    try:
        from utils.feeds_catalog import CITY_TO_COUNTRY
        return CITY_TO_COUNTRY
    except ImportError:
        print("❌ ERROR: Could not import CITY_TO_COUNTRY from feeds_catalog")
        sys.exit(1)

def find_wrong_locations(cursor, city_to_country):
    """Find alerts with impossible city/country combinations."""
    print("\n🔍 Scanning for invalid city/country combinations...")
    
    # Get all alerts with both city and country
    query = """
    SELECT id, uuid, title, city, country, source
    FROM alerts
    WHERE city IS NOT NULL 
      AND country IS NOT NULL
      AND city != ''
      AND country != ''
    ORDER BY id
    """
    
    cursor.execute(query)
    all_alerts = cursor.fetchall()
    
    wrong_locations = []
    fixable = []
    
    for alert in all_alerts:
        city = alert['city']
        country = alert['country']
        city_lower = city.lower().strip()
        
        # Check if we have a canonical country for this city
        canonical_country = city_to_country.get(city_lower)
        
        if canonical_country:
            # We have a mapping - check if it matches
            if canonical_country.lower() != country.lower():
                wrong_locations.append(alert)
                # This is fixable - we know the correct country
                fixable.append({
                    'id': alert['id'],
                    'uuid': alert['uuid'],
                    'city': city,
                    'wrong_country': country,
                    'correct_country': canonical_country,
                    'title': alert['title'][:80]
                })
    
    return wrong_locations, fixable

def fix_locations(cursor, fixable, dry_run=True):
    """Fix alerts by updating to correct country."""
    print(f"\n🔧 {'Would fix' if dry_run else 'Fixing'} {len(fixable)} alerts with wrong countries...")
    
    fixed_count = 0
    for item in fixable:
        print(f"\n📍 Alert ID {item['id']}")
        print(f"   City: {item['city']}")
        print(f"   Wrong country: {item['wrong_country']} ❌")
        print(f"   Correct country: {item['correct_country']} ✅")
        print(f"   Title: {item['title']}...")
        
        if not dry_run:
            # Update both alerts and raw_alerts tables
            update_query = """
            UPDATE alerts 
            SET country = %s, 
                updated_at = NOW()
            WHERE id = %s
            """
            cursor.execute(update_query, (item['correct_country'], item['id']))
            
            # Also update raw_alerts if exists
            raw_update = """
            UPDATE raw_alerts 
            SET country = %s 
            WHERE uuid = %s
            """
            cursor.execute(raw_update, (item['correct_country'], item['uuid']))
            
            fixed_count += 1
            print(f"   ✅ Fixed!")
    
    return fixed_count

def delete_unfixable(cursor, wrong_locations, fixable_ids, dry_run=True):
    """Delete alerts that can't be fixed (no mapping available)."""
    fixable_id_set = {item['id'] for item in fixable_ids}
    unfixable = [alert for alert in wrong_locations if alert['id'] not in fixable_id_set]
    
    if not unfixable:
        print("\n✨ No unfixable alerts found!")
        return 0
    
    print(f"\n🗑️  {'Would delete' if dry_run else 'Deleting'} {len(unfixable)} unfixable alerts...")
    
    deleted_count = 0
    for alert in unfixable:
        print(f"\n❌ Alert ID {alert['id']} - Cannot fix (no mapping)")
        print(f"   City: {alert['city']}, Country: {alert['country']}")
        print(f"   Title: {alert['title'][:80]}...")
        
        if not dry_run:
            # Delete from both tables
            cursor.execute("DELETE FROM alerts WHERE id = %s", (alert['id'],))
            cursor.execute("DELETE FROM raw_alerts WHERE uuid = %s", (alert['uuid'],))
            deleted_count += 1
            print(f"   🗑️  Deleted!")
    
    return deleted_count

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Clean up alerts with wrong locations')
    parser.add_argument('--execute', action='store_true', 
                       help='Actually fix/delete alerts (default is dry-run)')
    args = parser.parse_args()
    
    dry_run = not args.execute
    
    if dry_run:
        print("="*70)
        print("🔍 DRY RUN MODE - No changes will be made")
        print("   Run with --execute to actually fix/delete alerts")
        print("="*70)
    else:
        print("="*70)
        print("⚠️  EXECUTE MODE - Alerts will be FIXED/DELETED")
        print("="*70)
        response = input("Are you sure you want to modify the database? (yes/no): ")
        if response.lower() != 'yes':
            print("❌ Aborted")
            sys.exit(0)
    
    # Get mapping
    city_to_country = get_city_to_country_mapping()
    print(f"✅ Loaded {len(city_to_country)} city-to-country mappings")
    
    # Connect to database
    print("\n📡 Connecting to database...")
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # Find wrong locations
        wrong_locations, fixable = find_wrong_locations(cursor, city_to_country)
        
        print("\n" + "="*70)
        print("📊 SCAN RESULTS")
        print("="*70)
        print(f"Total alerts with wrong locations: {len(wrong_locations)}")
        print(f"  - Fixable (have mapping): {len(fixable)}")
        print(f"  - Unfixable (no mapping): {len(wrong_locations) - len(fixable)}")
        
        if not wrong_locations:
            print("\n✨ No wrong locations found! Database is clean.")
            return
        
        # Show examples
        print("\n📋 Examples of wrong locations:")
        for item in fixable[:5]:
            print(f"  • {item['city']}, {item['wrong_country']} → should be {item['correct_country']}")
        
        # Fix locations
        if fixable:
            fixed_count = fix_locations(cursor, fixable, dry_run)
        else:
            fixed_count = 0
        
        # Delete unfixable
        deleted_count = delete_unfixable(cursor, wrong_locations, fixable, dry_run)
        
        if not dry_run:
            conn.commit()
            print("\n✅ Changes committed to database")
        else:
            print("\n🔍 Dry run complete - no changes made")
        
        # Summary
        print("\n" + "="*70)
        print("🎉 CLEANUP SUMMARY")
        print("="*70)
        
        if dry_run:
            print(f"Would fix: {len(fixable)} alerts")
            print(f"Would delete: {len(wrong_locations) - len(fixable)} alerts")
            print(f"\nTotal changes: {len(wrong_locations)}")
        else:
            print(f"Fixed: {fixed_count} alerts")
            print(f"Deleted: {deleted_count} alerts")
            print(f"\nTotal changes: {fixed_count + deleted_count}")
        
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
