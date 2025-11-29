#!/usr/bin/env python3
"""
Emergency coordinate fix script
Geocodes alerts with NULL/0 coordinates using their country field
"""
import os
import sys
import time
import psycopg2
from typing import Dict, Optional
import requests

DATABASE_URL = os.getenv("DATABASE_URL")
OPENCAGE_API_KEY = os.getenv("OPENCAGE_API_KEY")

# Country centroids as fallback (no API calls needed)
COUNTRY_CENTROIDS = {
    'US': (39.8283, -98.5795),
    'USA': (39.8283, -98.5795),
    'UK': (55.3781, -3.4360),
    'GB': (55.3781, -3.4360),
    'FR': (46.2276, 2.2137),
    'DE': (51.1657, 10.4515),
    'CN': (35.8617, 104.1954),
    'IN': (20.5937, 78.9629),
    'BR': (-14.2350, -51.9253),
    'RU': (61.5240, 105.3188),
    'JP': (36.2048, 138.2529),
    'IT': (41.8719, 12.5674),
    'ES': (40.4637, -3.7492),
    'CA': (56.1304, -106.3468),
    'AU': (-25.2744, 133.7751),
    'MX': (23.6345, -102.5528),
    'KR': (35.9078, 127.7669),
    'ID': (-0.7893, 113.9213),
    'TR': (38.9637, 35.2433),
    'SA': (23.8859, 45.0792),
    'AR': (-38.4161, -63.6167),
    'ZA': (-30.5595, 22.9375),
    'EG': (26.8206, 30.8025),
    'PL': (51.9194, 19.1451),
    'UA': (48.3794, 31.1656),
    'PK': (30.3753, 69.3451),
    'NG': (9.0820, 8.6753),
    'BD': (23.6850, 90.3563),
    'IL': (31.0461, 34.8516),
    'IQ': (33.2232, 43.6793),
    'SY': (34.8021, 38.9968),
    'YE': (15.5527, 48.5164),
    'AF': (33.9391, 67.7100),
}

def geocode_country(country: str) -> Optional[Dict]:
    """Geocode country name to coordinates"""
    if not country:
        return None
    
    # Try country code lookup first (fast, no API)
    country_upper = country.strip().upper()
    if country_upper in COUNTRY_CENTROIDS:
        lat, lon = COUNTRY_CENTROIDS[country_upper]
        return {'lat': lat, 'lon': lon, 'source': 'centroid'}
    
    # Try OpenCage API
    if OPENCAGE_API_KEY:
        try:
            url = "https://api.opencagedata.com/geocode/v1/json"
            params = {
                'q': country,
                'key': OPENCAGE_API_KEY,
                'limit': 1,
                'no_annotations': 1
            }
            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('results'):
                    geo = data['results'][0]['geometry']
                    return {'lat': geo['lat'], 'lon': geo['lng'], 'source': 'opencage'}
        except Exception as e:
            print(f"  OpenCage API error for {country}: {e}")
    
    return None

def fix_coordinates(batch_size: int = 50, source_filter: Optional[str] = None):
    """Fix alerts with NULL/0 coordinates"""
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set")
        return
    
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    
    # Build source filter
    source_clause = ""
    if source_filter:
        source_clause = f"AND source = '{source_filter}'"
    
    # Get alerts needing geocoding
    cur.execute(f"""
        SELECT id, uuid, country, source
        FROM alerts
        WHERE (longitude IS NULL OR longitude = 0.0)
          AND country IS NOT NULL
          {source_clause}
        LIMIT %s
    """, (batch_size,))
    
    alerts = cur.fetchall()
    
    if not alerts:
        print("No alerts need geocoding")
        return
    
    print(f"Found {len(alerts)} alerts to geocode")
    
    geocoded = 0
    failed = 0
    
    for alert_id, uuid, country, source in alerts:
        result = geocode_country(country)
        
        if result:
            cur.execute("""
                UPDATE alerts
                SET latitude = %s, longitude = %s
                WHERE id = %s
            """, (result['lat'], result['lon'], alert_id))
            geocoded += 1
            print(f"  ✓ {uuid} ({source}): {country} → ({result['lon']:.4f}, {result['lat']:.4f}) [{result['source']}]")
            
            # Rate limit OpenCage API
            if result['source'] == 'opencage':
                time.sleep(0.5)  # 2 req/sec = under quota
        else:
            failed += 1
            print(f"  ✗ {uuid}: Failed to geocode '{country}'")
    
    conn.commit()
    cur.close()
    conn.close()
    
    print(f"\nResults: {geocoded} geocoded, {failed} failed")

if __name__ == "__main__":
    batch = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    source = sys.argv[2] if len(sys.argv) > 2 else None
    fix_coordinates(batch, source)
