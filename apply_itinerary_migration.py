#!/usr/bin/env python3
"""Apply travel itineraries migration to Railway database."""

import os
import psycopg2

def apply_itinerary_migration():
    db_url = os.environ.get("DATABASE_PUBLIC_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_PUBLIC_URL or DATABASE_URL not set")
        return False
    
    # Read migration file
    migration_path = "migrations/004_travel_risk_itineraries.sql"
    if not os.path.exists(migration_path):
        print(f"ERROR: Migration file not found: {migration_path}")
        return False
    
    with open(migration_path, 'r') as f:
        migration_sql = f.read()
    
    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = False
        cur = conn.cursor()
        
        print("Applying migration 004_travel_risk_itineraries.sql...")
        cur.execute(migration_sql)
        
        # Verify table creation
        cur.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' AND table_name = 'travel_itineraries'
        """)
        if cur.fetchone():
            print("✓ Table 'travel_itineraries' created successfully")
        else:
            print("✗ Table creation failed")
            conn.rollback()
            return False
        
        # Verify indexes
        cur.execute("""
            SELECT indexname FROM pg_indexes 
            WHERE tablename = 'travel_itineraries'
        """)
        indexes = cur.fetchall()
        print(f"✓ Created {len(indexes)} indexes: {[idx[0] for idx in indexes]}")
        
        # Verify view
        cur.execute("""
            SELECT table_name FROM information_schema.views 
            WHERE table_schema = 'public' AND table_name = 'active_itineraries'
        """)
        if cur.fetchone():
            print("✓ View 'active_itineraries' created successfully")
        
        # Verify trigger
        cur.execute("""
            SELECT tgname FROM pg_trigger 
            WHERE tgname = 'trigger_itinerary_updated_at'
        """)
        if cur.fetchone():
            print("✓ Trigger 'trigger_itinerary_updated_at' created successfully")
        
        conn.commit()
        print("\n✅ Migration applied successfully!")
        
        cur.close()
        conn.close()
        return True
        
    except psycopg2.Error as e:
        print(f"\n❌ Migration failed: {e}")
        if 'conn' in locals():
            conn.rollback()
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    success = apply_itinerary_migration()
    exit(0 if success else 1)
