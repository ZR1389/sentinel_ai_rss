#!/usr/bin/env python3
"""phase3_production_geocoding.py

Phase 3: Use EXISTING production geocoding infrastructure properly.

ROOT CAUSE: Phase 2 used standalone Nominatim instead of your production stack:
  1. location_service_consolidated.py (NLP extraction with 250+ cities)
  2. geocoding_service.py (Redis + PostgreSQL cache + Nominatim + OpenCage with 2,500/day quota)
  3. geocoded_locations table (already has 250 cached entries from OpenCage)

This phase properly uses your existing infrastructure and adds quality gating.

Usage:
  # Install missing library
  pip install opencage
  
  # Set API key if not already set
  export OPENCAGE_API_KEY=your_key_here
  
  # Run with production stack
  python scripts/phase3_production_geocoding.py --limit 100 --dry-run
  
  # Full batch with quality gating
  python scripts/phase3_production_geocoding.py --min-confidence 6
"""
import os
import sys
import argparse
from typing import Optional, Dict, Tuple
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, '/home/zika/sentinel_ai_rss')

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

def geocode_with_production_stack(title: str, summary: str, gpt_summary: str, en_snippet: str) -> Optional[Dict]:
    """
    Use the ACTUAL production geocoding stack that's already built.
    """
    try:
        # Step 1: Extract location using production NLP service
        from location_service_consolidated import detect_location
        
        text = f"{title or ''}\n{summary or ''}"
        location_result = detect_location(text)
        
        if not location_result or not (location_result.city or location_result.country):
            return None
        
        # Build location string for geocoding
        if location_result.city and location_result.country:
            location_string = f"{location_result.city}, {location_result.country}"
        elif location_result.city:
            location_string = location_result.city
        else:
            location_string = location_result.country
        
        # Step 2: Geocode using production service (Redis -> Postgres -> Nominatim -> OpenCage)
        from geocoding_service import geocode
        
        geo_result = geocode(location_string)
        
        if geo_result and geo_result.get('latitude') and geo_result.get('longitude'):
            return {
                'latitude': geo_result['latitude'],
                'longitude': geo_result['longitude'],
                'city': geo_result.get('city') or location_result.city,
                'country': geo_result.get('country') or location_result.country,
                'location_method': geo_result.get('source', 'production_stack'),
                'confidence': geo_result.get('confidence', 5)
            }
        
        return None
        
    except Exception as e:
        print(f"  ERROR geocoding: {e}")
        return None

def process_alerts(cur, limit: Optional[int], dry_run: bool, min_confidence: int):
    """
    Process alerts using production geocoding infrastructure.
    """
    # Target only alerts that FAILED in previous phases or have low confidence
    query = """
        SELECT id, title, summary, gpt_summary, en_snippet, location_method
        FROM alerts
        WHERE (latitude IS NULL OR longitude IS NULL)
          AND location_method IN ('unknown', 'low')
        ORDER BY created_at DESC
    """
    
    if limit:
        query += f" LIMIT {limit}"
    
    cur.execute(query)
    alerts = cur.fetchall()
    total = len(alerts)
    
    if total == 0:
        print("No alerts need geocoding!")
        return 0, 0, 0
    
    print(f"\n=== Phase 3: Production Geocoding Stack ===")
    print(f"Processing {total} alerts")
    print(f"Min confidence: {min_confidence}/10")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}\n")
    
    # Check infrastructure
    try:
        from location_service_consolidated import detect_location
        from geocoding_service import geocode, _redis_opencage_get_usage
        print("✓ location_service_consolidated loaded")
        print("✓ geocoding_service loaded")
        
        opencage_key = os.getenv('OPENCAGE_API_KEY')
        if opencage_key:
            usage = _redis_opencage_get_usage()
            remaining = 2500 - usage
            print(f"✓ OpenCage API key set (quota: {usage}/2500, remaining: {remaining})")
        else:
            print("⚠ OpenCage API key NOT set (will use Nominatim fallback)")
        print()
    except ImportError as e:
        print(f"✗ ERROR: Production infrastructure not available: {e}")
        print("\nInstall missing dependencies:")
        print("  pip install opencage redis")
        return 0, 0, 0
    
    geocoded = 0
    failed = 0
    rejected_low_confidence = 0
    batch_size = 50
    
    for i, alert in enumerate(alerts):
        aid = alert['id']
        title = alert['title']
        summary = alert['summary']
        gpt_summary = alert['gpt_summary']
        en_snippet = alert['en_snippet']
        
        # Geocode using production stack
        result = geocode_with_production_stack(title, summary, gpt_summary, en_snippet)
        
        if result:
            confidence = result.get('confidence', 5)
            
            # Quality gating: reject low-confidence results
            if confidence < min_confidence:
                rejected_low_confidence += 1
                if geocoded + rejected_low_confidence <= 10:
                    print(f"✗ [{rejected_low_confidence:4d}] LOW CONFIDENCE ({confidence}) - {title[:60]}")
                continue
            
            geocoded += 1
            
            if not dry_run:
                # Update database
                cur.execute("""
                    UPDATE alerts
                    SET 
                        latitude = %s,
                        longitude = %s,
                        city = COALESCE(NULLIF(%s, ''), city),
                        country = COALESCE(NULLIF(%s, ''), country),
                        location_method = %s,
                        location_confidence = %s,
                        updated_at = NOW()
                    WHERE id = %s
                """, (
                    result['latitude'],
                    result['longitude'],
                    result['city'],
                    result['country'],
                    result['location_method'],
                    'high' if confidence >= 8 else ('medium' if confidence >= 6 else 'low'),
                    aid
                ))
            
            # Print sample successes
            if geocoded <= 10 or geocoded % 50 == 0:
                title_short = (title[:60] + '...') if len(title) > 60 else title
                print(f"✓ [{geocoded:4d}] conf={confidence} {title_short} → {result['city']}, {result['country']}")
        else:
            failed += 1
        
        # Commit in batches
        if not dry_run and (i + 1) % batch_size == 0:
            cur.connection.commit()
            print(f"\nBatch: {i+1}/{total} | Geocoded: {geocoded} | Rejected: {rejected_low_confidence} | Failed: {failed}\n")
        
        # Progress updates
        if (i + 1) % 100 == 0:
            pct = (i + 1) / total * 100
            print(f"Progress: {i+1}/{total} ({pct:.1f}%) | Geocoded: {geocoded} | Rejected: {rejected_low_confidence} | Failed: {failed}")
    
    # Final commit
    if not dry_run:
        cur.connection.commit()
    
    return geocoded, rejected_low_confidence, failed

def main():
    parser = argparse.ArgumentParser(description='Phase 3: Production geocoding with quality gating')
    parser.add_argument('--limit', type=int, help='Limit number of alerts to process')
    parser.add_argument('--dry-run', action='store_true', help='Show results without updating database')
    parser.add_argument('--min-confidence', type=int, default=6, help='Minimum confidence score (1-10, default 6)')
    args = parser.parse_args()

    load_env()
    
    with get_conn() as conn:
        conn.autocommit = False
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            geocoded, rejected, failed = process_alerts(cur, args.limit, args.dry_run, args.min_confidence)
            
            print(f"\n=== Results ===")
            total = geocoded + rejected + failed
            if total > 0:
                print(f"Geocoded (quality pass): {geocoded}/{total} ({geocoded/total*100:.1f}%)")
                print(f"Rejected (low confidence): {rejected}/{total} ({rejected/total*100:.1f}%)")
                print(f"Failed (no extraction): {failed}/{total} ({failed/total*100:.1f}%)")
            
            if not args.dry_run and geocoded > 0:
                # Check new overall coverage
                cur.execute("""
                    SELECT 
                        COUNT(*) as total,
                        SUM(CASE WHEN latitude IS NOT NULL AND longitude IS NOT NULL THEN 1 ELSE 0 END) as with_coords
                    FROM alerts
                """)
                result = cur.fetchone()
                coverage = (result['with_coords'] / result['total'] * 100) if result['total'] > 0 else 0
                print(f"\nOverall coordinate coverage: {result['with_coords']}/{result['total']} ({coverage:.1f}%)")
            elif args.dry_run:
                print("\nDry-run complete; no database changes made.")

if __name__ == '__main__':
    main()
