#!/usr/bin/env python3
"""phase2_nlp_geocoding.py

Phase 2: Extract locations from title/summary/content text and geocode them.

Current status after Phase 1:
- 757/1,511 alerts have coordinates (50.1%)
- 754 alerts still need geocoding:
  - unknown: 711 missing
  - low: 43 missing

Strategy:
1. Pattern matching for "in CITY, COUNTRY" or "CITY, COUNTRY - headline"
2. Known location keyword search (conflict zones, major cities)
3. Fallback to capitalized word extraction
4. Geocode using Nominatim (1 req/sec limit)

Optional: Use OpenCage API for faster/better results (if API key available)

Usage:
  # Test on 50 alerts
  python scripts/phase2_nlp_geocoding.py --limit 50 --dry-run
  
  # Full run
  python scripts/phase2_nlp_geocoding.py
  
  # With OpenCage API (faster, better quality)
  OPENCAGE_API_KEY=your_key python scripts/phase2_nlp_geocoding.py --use-opencage
"""
import os
import re
import time
import argparse
from typing import Optional, Dict
import psycopg2
from dotenv import load_dotenv

# Nominatim geocoder
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

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

# Curated location database (conflict zones + major cities)
KNOWN_LOCATIONS = {
    # Conflict zones (high priority)
    'kyiv': 'Kyiv, Ukraine',
    'kiev': 'Kyiv, Ukraine',
    'kharkiv': 'Kharkiv, Ukraine',
    'lviv': 'Lviv, Ukraine',
    'donetsk': 'Donetsk, Ukraine',
    'mariupol': 'Mariupol, Ukraine',
    'odesa': 'Odessa, Ukraine',
    'odessa': 'Odessa, Ukraine',
    
    'moscow': 'Moscow, Russia',
    'st petersburg': 'Saint Petersburg, Russia',
    'saint petersburg': 'Saint Petersburg, Russia',
    'volgograd': 'Volgograd, Russia',
    
    'gaza': 'Gaza City, Gaza Strip',
    'tel aviv': 'Tel Aviv, Israel',
    'jerusalem': 'Jerusalem, Israel',
    'haifa': 'Haifa, Israel',
    
    'beirut': 'Beirut, Lebanon',
    'damascus': 'Damascus, Syria',
    'aleppo': 'Aleppo, Syria',
    'homs': 'Homs, Syria',
    
    'baghdad': 'Baghdad, Iraq',
    'mosul': 'Mosul, Iraq',
    'basra': 'Basra, Iraq',
    
    'kabul': 'Kabul, Afghanistan',
    'kandahar': 'Kandahar, Afghanistan',
    
    'tehran': 'Tehran, Iran',
    'isfahan': 'Isfahan, Iran',
    
    'sanaa': 'Sanaa, Yemen',
    "sana'a": 'Sanaa, Yemen',
    'aden': 'Aden, Yemen',
    
    'tripoli': 'Tripoli, Libya',
    'benghazi': 'Benghazi, Libya',
    
    'mogadishu': 'Mogadishu, Somalia',
    'khartoum': 'Khartoum, Sudan',
    
    # Major world cities
    'paris': 'Paris, France',
    'london': 'London, United Kingdom',
    'berlin': 'Berlin, Germany',
    'rome': 'Rome, Italy',
    'madrid': 'Madrid, Spain',
    'vienna': 'Vienna, Austria',
    'warsaw': 'Warsaw, Poland',
    'prague': 'Prague, Czech Republic',
    'athens': 'Athens, Greece',
    'budapest': 'Budapest, Hungary',
    
    'new york': 'New York, USA',
    'washington': 'Washington DC, USA',
    'los angeles': 'Los Angeles, USA',
    'chicago': 'Chicago, USA',
    'san francisco': 'San Francisco, USA',
    
    'beijing': 'Beijing, China',
    'shanghai': 'Shanghai, China',
    'hong kong': 'Hong Kong',
    'tokyo': 'Tokyo, Japan',
    'seoul': 'Seoul, South Korea',
    'taipei': 'Taipei, Taiwan',
    
    'mumbai': 'Mumbai, India',
    'new delhi': 'New Delhi, India',
    'delhi': 'Delhi, India',
    'bangalore': 'Bangalore, India',
    'kolkata': 'Kolkata, India',
    'chennai': 'Chennai, India',
    'hyderabad': 'Hyderabad, India',
    
    'bangkok': 'Bangkok, Thailand',
    'singapore': 'Singapore',
    'jakarta': 'Jakarta, Indonesia',
    'manila': 'Manila, Philippines',
    'hanoi': 'Hanoi, Vietnam',
    'kuala lumpur': 'Kuala Lumpur, Malaysia',
    
    'cairo': 'Cairo, Egypt',
    'lagos': 'Lagos, Nigeria',
    'nairobi': 'Nairobi, Kenya',
    'johannesburg': 'Johannesburg, South Africa',
    'cape town': 'Cape Town, South Africa',
    
    'sao paulo': 'Sao Paulo, Brazil',
    'rio de janeiro': 'Rio de Janeiro, Brazil',
    'buenos aires': 'Buenos Aires, Argentina',
    'mexico city': 'Mexico City, Mexico',
    'santiago': 'Santiago, Chile',
    'bogota': 'Bogota, Colombia',
    
    'sydney': 'Sydney, Australia',
    'melbourne': 'Melbourne, Australia',
    'brisbane': 'Brisbane, Australia',
    'perth': 'Perth, Australia',
    'auckland': 'Auckland, New Zealand',
    
    'toronto': 'Toronto, Canada',
    'vancouver': 'Vancouver, Canada',
    'montreal': 'Montreal, Canada',
}

def extract_location_from_text(title: str, summary: str, gpt_summary: str, en_snippet: str) -> Optional[str]:
    """
    Extract location name from article text using multiple strategies.
    Returns location string for geocoding, or None if not found.
    
    Note: 'content' column doesn't exist; using gpt_summary + en_snippet instead.
    """
    text_lower = f"{title or ''} {summary or ''} {gpt_summary or ''} {en_snippet or ''}".lower()
    text_original = f"{title or ''} {summary or ''}"
    
    # Strategy 1: Pattern matching for common news formats
    patterns = [
        r'\bin\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*,\s*([A-Z][a-z]+)',  # "in Kyiv, Ukraine"
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*,\s*([A-Z][a-z]+)\s*[-–—]',  # "Kyiv, Ukraine - "
        r'\(([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\)\s*[-–—]',  # "(Tel Aviv) - "
        r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*[-–—]',  # "Tel Aviv - " at start
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text_original)
        if match:
            location = match.group(1).strip()
            location_lower = location.lower()
            
            # Check if it's a known location
            if location_lower in KNOWN_LOCATIONS:
                return KNOWN_LOCATIONS[location_lower]
            
            # Try with second group if available (city + country)
            if match.lastindex >= 2:
                city = match.group(1).strip()
                country = match.group(2).strip()
                return f"{city}, {country}"
    
    # Strategy 2: Known location keyword search
    # Sort by length (longest first) to avoid substring matches
    sorted_locations = sorted(KNOWN_LOCATIONS.items(), key=lambda x: len(x[0]), reverse=True)
    
    for keyword, full_location in sorted_locations:
        # Use word boundaries to avoid false matches
        if re.search(rf'\b{re.escape(keyword)}\b', text_lower):
            return full_location
    
    # Strategy 3: Extract capitalized words that might be cities
    caps_words = re.findall(r'\b([A-Z][a-z]{3,}(?:\s+[A-Z][a-z]+)?)\b', text_original)
    for word in caps_words[:5]:  # Check first 5
        word_lower = word.lower()
        if word_lower in KNOWN_LOCATIONS:
            return KNOWN_LOCATIONS[word_lower]
    
    return None

def geocode_nominatim(location_string: str) -> Optional[Dict]:
    """
    Geocode using Nominatim (OSM) with retry logic.
    Rate limit: 1 request/second
    """
    geolocator = Nominatim(user_agent="sentinel-ai-phase2", timeout=5)
    max_retries = 3
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            geo = geolocator.geocode(location_string)
            if geo:
                address_parts = geo.address.split(',')
                city = address_parts[0].strip() if address_parts else None
                country = address_parts[-1].strip() if len(address_parts) > 1 else None
                
                return {
                    'latitude': geo.latitude,
                    'longitude': geo.longitude,
                    'city': city,
                    'country': country,
                    'location_method': 'nlp_nominatim'
                }
        except GeocoderTimedOut:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                retry_delay *= 2
                continue
        except GeocoderServiceError:
            pass
    
    return None

def geocode_opencage(location_string: str, api_key: str) -> Optional[Dict]:
    """
    Geocode using OpenCage API (better quality, higher rate limits).
    Rate limit: 1 request/second (free tier)
    """
    try:
        from opencage.geocoder import OpenCageGeocode
    except ImportError:
        print("OpenCage library not installed. Run: pip install opencage")
        return None
    
    geocoder = OpenCageGeocode(api_key)
    
    try:
        results = geocoder.geocode(location_string)
        if results and len(results) > 0:
            result = results[0]
            geo = result['geometry']
            components = result['components']
            
            return {
                'latitude': geo['lat'],
                'longitude': geo['lng'],
                'city': components.get('city') or components.get('town') or components.get('village'),
                'country': components.get('country'),
                'location_method': 'nlp_opencage'
            }
    except Exception as e:
        print(f"OpenCage error for '{location_string}': {e}")
    
    return None

def process_alerts(cur, limit: Optional[int], dry_run: bool, use_opencage: bool):
    """
    Process alerts with missing coordinates using NLP extraction + geocoding.
    """
    # Get alerts needing geocoding (use columns that exist: title, summary, gpt_summary, en_snippet)
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
        return 0, 0
    
    print(f"\n=== Phase 2: NLP Geocoding ===")
    print(f"Processing {total} alerts")
    print(f"Geocoder: {'OpenCage' if use_opencage else 'Nominatim (OSM)'}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}\n")
    
    # Setup geocoder
    opencage_key = os.getenv('OPENCAGE_API_KEY') if use_opencage else None
    if use_opencage and not opencage_key:
        print("WARNING: --use-opencage specified but OPENCAGE_API_KEY not set. Falling back to Nominatim.")
        use_opencage = False
    
    geocoded = 0
    failed = 0
    batch_size = 50
    
    for i, (aid, title, summary, gpt_summary, en_snippet, method) in enumerate(alerts):
        # Extract location from text
        location_string = extract_location_from_text(title, summary, gpt_summary, en_snippet)
        
        if not location_string:
            failed += 1
            if (i + 1) % 100 == 0:
                print(f"Progress: {i+1}/{total} | Geocoded: {geocoded} | Failed: {failed}")
            continue
        
        # Geocode
        if use_opencage:
            result = geocode_opencage(location_string, opencage_key)
        else:
            result = geocode_nominatim(location_string)
        
        if result:
            geocoded += 1
            
            if not dry_run:
                # Update database
                cur.execute("""
                    UPDATE alerts
                    SET 
                        latitude = %s,
                        longitude = %s,
                        city = COALESCE(NULLIF(city, ''), %s),
                        country = COALESCE(NULLIF(country, ''), %s),
                        location_method = %s,
                        updated_at = NOW()
                    WHERE id = %s
                """, (
                    result['latitude'],
                    result['longitude'],
                    result['city'],
                    result['country'],
                    result['location_method'],
                    aid
                ))
            
            # Print sample successes
            if geocoded <= 10 or geocoded % 50 == 0:
                title_short = (title[:60] + '...') if len(title) > 60 else title
                print(f"✓ [{geocoded:4d}] {title_short} → {result['city']}, {result['country']}")
        else:
            failed += 1
        
        # Commit in batches
        if not dry_run and (i + 1) % batch_size == 0:
            cur.connection.commit()
            print(f"\nBatch commit: {i+1}/{total} | Geocoded: {geocoded} | Failed: {failed}\n")
        
        # Progress updates
        if (i + 1) % 100 == 0:
            pct = (i + 1) / total * 100
            print(f"Progress: {i+1}/{total} ({pct:.1f}%) | Geocoded: {geocoded} | Failed: {failed}")
        
        # Rate limiting (Nominatim requires 1 req/sec)
        if not use_opencage and result:
            time.sleep(1.1)
    
    # Final commit
    if not dry_run:
        cur.connection.commit()
    
    return geocoded, failed

def main():
    parser = argparse.ArgumentParser(description='Phase 2: NLP location extraction + geocoding')
    parser.add_argument('--limit', type=int, help='Limit number of alerts to process')
    parser.add_argument('--dry-run', action='store_true', help='Show results without updating database')
    parser.add_argument('--use-opencage', action='store_true', help='Use OpenCage API instead of Nominatim')
    args = parser.parse_args()

    load_env()
    
    with get_conn() as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            geocoded, failed = process_alerts(cur, args.limit, args.dry_run, args.use_opencage)
            
            print(f"\n=== Results ===")
            total = geocoded + failed
            if total > 0:
                print(f"Geocoded: {geocoded}/{total} ({geocoded/total*100:.1f}%)")
                print(f"Failed: {failed}/{total} ({failed/total*100:.1f}%)")
            
            if not args.dry_run and geocoded > 0:
                # Check new overall coverage
                cur.execute("""
                    SELECT 
                        COUNT(*) as total,
                        SUM(CASE WHEN latitude IS NOT NULL AND longitude IS NOT NULL THEN 1 ELSE 0 END) as with_coords
                    FROM alerts
                """)
                result = cur.fetchone()
                coverage = (result[1] / result[0] * 100) if result[0] > 0 else 0
                print(f"\nOverall coordinate coverage: {result[1]}/{result[0]} ({coverage:.1f}%)")
            elif args.dry_run:
                print("\nDry-run complete; no database changes made.")

if __name__ == '__main__':
    main()
