#!/usr/bin/env python3
"""
Run OpenCage geocoding migration on Railway PostgreSQL.
Applies PostGIS schema updates to existing database.
"""
import os
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

def run_migration():
    db_url = os.getenv('DATABASE_URL')
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)
    
    print(f"Connecting to database...")
    conn = psycopg2.connect(db_url)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    
    # Read migration SQL
    with open('migrate_opencage_geocoding.sql', 'r') as f:
        migration_sql = f.read()
    
    print("Running OpenCage geocoding migration...")
    try:
        cur.execute(migration_sql)
        print("✓ Migration completed successfully")
    except Exception as e:
        print(f"✗ Migration failed: {e}")
        sys.exit(1)
    
    # Verification
    print("\nVerifying schema...")
    
    # Check PostGIS
    cur.execute("SELECT PostGIS_Version();")
    pg_version = cur.fetchone()[0]
    print(f"✓ PostGIS version: {pg_version}")
    
    # Check tables
    cur.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name IN ('geocoded_locations', 'traveler_profiles', 'proximity_alerts', 'geocoding_quota_log')
        ORDER BY table_name;
    """)
    tables = [r[0] for r in cur.fetchall()]
    print(f"✓ Created tables: {', '.join(tables)}")
    
    # Check geom columns
    cur.execute("""
        SELECT table_name, column_name 
        FROM information_schema.columns 
        WHERE table_schema = 'public' 
        AND table_name IN ('alerts', 'raw_alerts') 
        AND column_name = 'geom'
        ORDER BY table_name;
    """)
    geom_cols = cur.fetchall()
    for table, col in geom_cols:
        print(f"✓ Added {col} column to {table}")
    
    # Check spatial indexes
    cur.execute("""
        SELECT indexname FROM pg_indexes 
        WHERE schemaname = 'public' 
        AND indexname LIKE '%geom%'
        ORDER BY indexname;
    """)
    indexes = [r[0] for r in cur.fetchall()]
    print(f"✓ Created {len(indexes)} spatial indexes")
    
    # Count existing alerts with lat/lon
    cur.execute("SELECT COUNT(*) FROM alerts WHERE latitude IS NOT NULL AND longitude IS NOT NULL;")
    alert_count = cur.fetchone()[0]
    print(f"\nℹ {alert_count} alerts have coordinates (ready for geom backfill)")
    
    cur.execute("SELECT COUNT(*) FROM raw_alerts WHERE latitude IS NOT NULL AND longitude IS NOT NULL;")
    raw_count = cur.fetchone()[0]
    print(f"ℹ {raw_count} raw_alerts have coordinates (ready for geom backfill)")
    
    cur.close()
    conn.close()
    
    print("\n" + "="*60)
    print("MIGRATION COMPLETE")
    print("="*60)
    print("\nNext steps:")
    print("1. Backfill geom columns from existing lat/lon:")
    print("   python backfill_geom.py")
    print("2. Test spatial queries:")
    print("   SELECT * FROM find_threats_near_location(6.5244, 3.3792, 50, 7);")
    print("3. Deploy OpenCage geocoding service")

if __name__ == "__main__":
    run_migration()
