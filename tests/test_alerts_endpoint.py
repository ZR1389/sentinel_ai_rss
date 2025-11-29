#!/usr/bin/env python3
"""Test /alerts/latest endpoint to diagnose map data issues"""

import os
import sys
import psycopg2
from psycopg2.extras import RealDictCursor

# Get DATABASE_URL from environment
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

print(f"Connecting to database...")
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor(cursor_factory=RealDictCursor)

# Check total alerts
cur.execute("SELECT COUNT(*) as total FROM alerts")
total = cur.fetchone()['total']
print(f"✓ Total alerts in database: {total}")

# Check alerts with coordinates
cur.execute("""
    SELECT COUNT(*) as with_coords 
    FROM alerts 
    WHERE latitude IS NOT NULL 
      AND longitude IS NOT NULL
""")
with_coords = cur.fetchone()['with_coords']
print(f"✓ Alerts with lat/lon: {with_coords}")

# Check recent alerts (last 7 days)
cur.execute("""
    SELECT COUNT(*) as recent 
    FROM alerts 
    WHERE published >= NOW() - INTERVAL '7 days'
""")
recent = cur.fetchone()['recent']
print(f"✓ Alerts from last 7 days: {recent}")

# Check recent alerts WITH coordinates
cur.execute("""
    SELECT COUNT(*) as recent_with_coords 
    FROM alerts 
    WHERE published >= NOW() - INTERVAL '7 days'
      AND latitude IS NOT NULL 
      AND longitude IS NOT NULL
""")
recent_coords = cur.fetchone()['recent_with_coords']
print(f"✓ Recent alerts WITH coordinates: {recent_coords}")

# Sample 5 recent alerts with coords
cur.execute("""
    SELECT uuid, published, source, country, city, latitude, longitude, score
    FROM alerts 
    WHERE published >= NOW() - INTERVAL '7 days'
      AND latitude IS NOT NULL 
      AND longitude IS NOT NULL
    ORDER BY published DESC
    LIMIT 5
""")
samples = cur.fetchall()
print(f"\n📍 Sample recent alerts:")
for row in samples:
    print(f"  - {row['country']}/{row['city']}: [{row['latitude']}, {row['longitude']}] score={row['score']} source={row['source']}")

cur.close()
conn.close()

print("\n" + "="*60)
if recent_coords == 0:
    print("❌ ISSUE FOUND: No recent alerts with coordinates!")
    print("   Possible causes:")
    print("   1. No data ingestion in last 7 days")
    print("   2. Geocoding not working (latitude/longitude NULL)")
    print("   3. RSS/ACLED sources not running")
else:
    print(f"✅ Database OK: {recent_coords} mappable alerts available")
    print("   If frontend still shows empty, check:")
    print("   1. /alerts/latest endpoint query filters")
    print("   2. Auth token validation")
    print("   3. Response serialization (dates, NULLs)")
