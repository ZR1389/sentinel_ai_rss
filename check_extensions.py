#!/usr/bin/env python3
"""
Check what PostgreSQL extensions are available and installed.
"""
import psycopg2
import os

def check_extensions():
    db_url = os.getenv("DATABASE_URL")
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    
    print("\n=== Available Extensions ===")
    cur.execute("""
        SELECT name, default_version, installed_version, comment
        FROM pg_available_extensions
        WHERE name LIKE '%postgis%' OR name LIKE '%spatial%'
        ORDER BY name;
    """)
    
    available = cur.fetchall()
    if available:
        for ext in available:
            name, default_ver, installed_ver, comment = ext
            status = f"INSTALLED ({installed_ver})" if installed_ver else "NOT INSTALLED"
            print(f"  {name:30s} {status:20s} [{default_ver}]")
            if comment:
                print(f"    └─ {comment[:80]}")
    else:
        print("  No PostGIS extensions found")
    
    print("\n=== Currently Installed Extensions ===")
    cur.execute("""
        SELECT extname, extversion
        FROM pg_extension
        ORDER BY extname;
    """)
    
    installed = cur.fetchall()
    for ext_name, ext_version in installed:
        print(f"  {ext_name:30s} {ext_version}")
    
    print("\n=== PostgreSQL Version ===")
    cur.execute("SELECT version();")
    print(f"  {cur.fetchone()[0]}")
    
    cur.close()
    conn.close()

if __name__ == "__main__":
    check_extensions()
