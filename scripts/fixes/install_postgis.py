#!/usr/bin/env python3
"""
Check and install PostGIS extension
"""
import os
import sys

# Add app to path for imports
sys.path.insert(0, '/app' if os.path.exists('/app') else os.getcwd())

from utils.db_utils import _get_db_connection

def check_and_install_postgis():
    """Check if PostGIS is installed, install if not"""
    try:
        with _get_db_connection() as conn:
            cur = conn.cursor()
            
            # Check current extensions
            cur.execute("""
                SELECT extname, extversion 
                FROM pg_extension 
                WHERE extname IN ('postgis', 'postgis_topology');
            """)
            rows = cur.fetchall()
            
            if rows:
                print("✓ PostGIS extensions already installed:")
                for row in rows:
                    print(f"  - {row[0]}: v{row[1]}")
                cur.close()
                return True
            
            print("PostGIS not found. Installing...")
            
            # Install PostGIS
            cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
            conn.commit()
            print("✓ PostGIS extension installed")
            
            # Verify installation
            cur.execute("SELECT PostGIS_Version();")
            version = cur.fetchone()
            if version:
                print(f"✓ PostGIS version: {version[0]}")
            
            cur.close()
            return True
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = check_and_install_postgis()
    sys.exit(0 if success else 1)
