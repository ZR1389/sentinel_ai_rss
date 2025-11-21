#!/usr/bin/env python3
"""phase1_fix_coordinate_gaps.py

Phase 1: Detect and categorize coordinate gaps in alerts table.

Your current status:
- location_method='coordinates' → 207 alerts, 0 missing (100% complete)
- location_method='moderate'   → 17 alerts, 0 missing (100% complete)
- location_method='low'        → 149 alerts, 143 missing (96% gap)
- location_method='unknown'    → 1138 alerts, 888 missing (78% gap)

Root cause analysis:
  Tags are text[] category labels (['physical_safety','terrorism']), 
  NOT structured metadata with lat/lon keys.
  
Phase 1 goal: Identify alerts where coordinates might be recoverable from:
  1. Country name → country centroid fallback
  2. City name with known coordinates in geocoded_locations table
  3. Metadata inspection (if any source stores coords in custom fields)

This script does NOT geocode text. That's Phase 2 (NLP extraction + geocoding APIs).

Usage:
  python scripts/phase1_fix_coordinate_gaps.py --dry-run
  python scripts/phase1_fix_coordinate_gaps.py --apply-country-fallback
"""
import os
import argparse
from typing import Dict, List, Tuple
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

def load_env():
    if os.path.exists('.env.production'):
        load_dotenv('.env.production', override=True)
    else:
        load_dotenv('.env', override=False)

def get_conn():
    url = os.getenv('DATABASE_URL')
    if not url:
        raise SystemExit('DATABASE_URL not set')
    return psycopg2.connect(url)

# Country centroid fallback (simplified subset; expand as needed)
COUNTRY_CENTROIDS = {
    'Ukraine': (48.3794, 31.1656),
    'Russia': (61.5240, 105.3188),
    'United States': (37.0902, -95.7129),
    'Brazil': (-14.2350, -51.9253),
    'Israel': (31.0461, 34.8516),
    'Iran': (32.4279, 53.6880),
    'India': (20.5937, 78.9629),
    'Australia': (-25.2744, 133.7751),
    'Finland': (61.9241, 25.7482),
    'France': (46.2276, 2.2137),
    'Germany': (51.1657, 10.4515),
    'Greece': (39.0742, 21.8243),
    'Nigeria': (9.0820, 8.6753),
    'Pakistan': (30.3753, 69.3451),
    'United Kingdom': (55.3781, -3.4360),
    'Italy': (41.8719, 12.5674),
    'Norway': (60.4720, 8.4689),
    'Serbia': (44.0165, 21.0059),
    'Argentina': (-38.4161, -63.6167),
    'Philippines': (12.8797, 121.7740),
    'Czechia': (49.8175, 15.4730),
    'Czech Republic': (49.8175, 15.4730),
    'Belarus': (53.7098, 27.9534),
    'Benin': (9.3077, 2.3158),
    'Bulgaria': (42.7339, 25.4858),
    'Hungary': (47.1625, 19.5033),
    'Estonia': (58.5953, 25.0136),
    'Belgium': (50.5039, 4.4699),
    'Thailand': (15.8700, 100.9925),
    'Singapore': (1.3521, 103.8198),
    'Canada': (56.1304, -106.3468),
    'Switzerland': (46.8182, 8.2275),
    'Austria': (47.5162, 14.5501),
    'Croatia': (45.1, 15.2),
    'Poland': (51.9194, 19.1451),
}

def analyze_gaps(cur) -> Dict:
    """Return breakdown of coordinate gaps by location_method and recovery options."""
    cur.execute("""
        SELECT 
            location_method,
            COUNT(*) as total,
            SUM(CASE WHEN latitude IS NULL OR longitude IS NULL THEN 1 ELSE 0 END) as missing,
            SUM(CASE WHEN (latitude IS NULL OR longitude IS NULL) 
                     AND country IS NOT NULL AND country <> '' THEN 1 ELSE 0 END) as recoverable_country,
            SUM(CASE WHEN (latitude IS NULL OR longitude IS NULL)
                     AND city IS NOT NULL AND city <> '' THEN 1 ELSE 0 END) as recoverable_city
        FROM alerts
        GROUP BY location_method
        ORDER BY missing DESC
    """)
    rows = cur.fetchall()
    result = {}
    for method, total, missing, rec_country, rec_city in rows:
        result[method or 'NULL'] = {
            'total': total,
            'missing': missing,
            'recoverable_country': rec_country,
            'recoverable_city': rec_city
        }
    return result

def apply_country_fallback(cur, dry_run: bool) -> int:
    """Apply country centroid coordinates to alerts missing lat/lon but having valid country."""
    cur.execute("""
        SELECT id, country
        FROM alerts
        WHERE (latitude IS NULL OR longitude IS NULL)
          AND country IS NOT NULL AND country <> ''
    """)
    candidates = cur.fetchall()
    updates = []
    for aid, country in candidates:
        if country in COUNTRY_CENTROIDS:
            lat, lon = COUNTRY_CENTROIDS[country]
            updates.append((lat, lon, 'country_centroid', aid))
    
    if not updates:
        return 0
    
    if dry_run:
        print(f"Dry-run: Would update {len(updates)} alerts with country centroids")
        # Show sample
        for i, (lat, lon, method, aid) in enumerate(updates[:5]):
            print(f"  Alert {aid}: lat={lat}, lon={lon}, method={method}")
        if len(updates) > 5:
            print(f"  ... and {len(updates)-5} more")
        return len(updates)
    
    execute_values(cur,
        """
        UPDATE alerts AS a SET
            latitude = v.lat,
            longitude = v.lon,
            location_method = v.method
        FROM (VALUES %s) AS v(lat, lon, method, id)
        WHERE a.id = v.id
        """,
        updates
    )
    return len(updates)

def apply_city_lookup(cur, dry_run: bool) -> int:
    """Match city name to geocoded_locations table if available."""
    # Check if geocoded_locations exists
    cur.execute("SELECT to_regclass('public.geocoded_locations')")
    if cur.fetchone()[0] is None:
        print("geocoded_locations table does not exist; skipping city lookup.")
        return 0
    
    cur.execute("""
        SELECT a.id, a.city, a.country, g.latitude, g.longitude
        FROM alerts a
        JOIN geocoded_locations g ON LOWER(a.city) = LOWER(g.city)
        WHERE (a.latitude IS NULL OR a.longitude IS NULL)
          AND a.city IS NOT NULL AND a.city <> ''
          AND g.latitude IS NOT NULL AND g.longitude IS NOT NULL
    """)
    matches = cur.fetchall()
    if not matches:
        return 0
    
    updates = [(lat, lon, 'city_lookup', aid) for aid, city, country, lat, lon in matches]
    
    if dry_run:
        print(f"Dry-run: Would update {len(updates)} alerts via city lookup")
        for i, (lat, lon, method, aid) in enumerate(updates[:5]):
            print(f"  Alert {aid}: lat={lat}, lon={lon}, method={method}")
        if len(updates) > 5:
            print(f"  ... and {len(updates)-5} more")
        return len(updates)
    
    execute_values(cur,
        """
        UPDATE alerts AS a SET
            latitude = v.lat,
            longitude = v.lon,
            location_method = v.method
        FROM (VALUES %s) AS v(lat, lon, method, id)
        WHERE a.id = v.id
        """,
        updates
    )
    return len(updates)

def main():
    parser = argparse.ArgumentParser(description='Phase 1: Coordinate gap analysis & fallback')
    parser.add_argument('--dry-run', action='store_true', help='Show changes without applying')
    parser.add_argument('--apply-country-fallback', action='store_true', help='Apply country centroids')
    parser.add_argument('--apply-city-lookup', action='store_true', help='Apply city coordinate lookup')
    args = parser.parse_args()

    load_env()
    with get_conn() as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            gaps = analyze_gaps(cur)
            print("=== Coordinate Gap Analysis ===")
            for method, stats in gaps.items():
                print(f"{method:20s}: {stats['missing']:4d}/{stats['total']:4d} missing "
                      f"(country_fallback={stats['recoverable_country']:4d}, city_lookup={stats['recoverable_city']:4d})")
            
            total_updated = 0
            if args.apply_country_fallback:
                print("\n=== Applying Country Centroids ===")
                updated = apply_country_fallback(cur, args.dry_run)
                print(f"Updated {updated} alerts with country centroids")
                total_updated += updated
            
            if args.apply_city_lookup:
                print("\n=== Applying City Lookup ===")
                updated = apply_city_lookup(cur, args.dry_run)
                print(f"Updated {updated} alerts via city lookup")
                total_updated += updated
            
            if not args.dry_run and total_updated > 0:
                conn.commit()
                print(f"\nCommitted {total_updated} updates.")
            elif args.dry_run:
                print("\nDry-run complete; no changes written.")
            else:
                print("\nNo updates applied (use --apply-country-fallback or --apply-city-lookup).")

if __name__ == '__main__':
    main()
