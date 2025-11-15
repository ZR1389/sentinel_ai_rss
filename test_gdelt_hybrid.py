#!/usr/bin/env python3
"""
GDELT Hybrid System Test
Demonstrates the complete query layer on top of production ingestion
"""

import sys
from gdelt_query import GDELTQuery

def test_location_query():
    """Test 1: Threats near specific coordinates"""
    print("\n" + "="*70)
    print("TEST 1: Location-Based Threat Query")
    print("="*70)
    
    # Test multiple potential conflict zones
    locations = [
        ("Kyiv, Ukraine", 50.4501, 30.5234),
        ("Gaza City", 31.5, 34.47),
        ("Damascus, Syria", 33.5138, 36.2765),
        ("Kabul, Afghanistan", 34.5553, 69.2075),
    ]
    
    for name, lat, lon in locations:
        print(f"\n📍 {name} ({lat}, {lon})")
        threats = GDELTQuery.get_threats_near_location(lat, lon, radius_km=100, days=7)
        
        if threats:
            print(f"   Found {len(threats)} threats within 100km (last 7 days):")
            for t in threats[:3]:  # Show top 3
                print(f"   • {t['date']}: {t['actor1']} vs {t['actor2']}")
                print(f"     Severity: {t['severity']}, Articles: {t['articles']}, "
                      f"Distance: {t['distance_km']}km")
        else:
            print(f"   ✓ No recent threats detected")


def test_country_summaries():
    """Test 2: Country-level threat aggregation"""
    print("\n" + "="*70)
    print("TEST 2: Country Threat Summaries")
    print("="*70)
    
    countries = {
        'UA': 'Ukraine',
        'IL': 'Israel',
        'SY': 'Syria',
        'AF': 'Afghanistan',
        'IQ': 'Iraq',
        'RU': 'Russia',
        'US': 'United States'
    }
    
    for code, name in countries.items():
        summary = GDELTQuery.get_country_summary(code, days=30)
        
        if summary:
            print(f"\n🌍 {name} ({code}) - Last 30 days:")
            print(f"   Total Events: {summary['total_events']}")
            print(f"   Avg Severity: {summary['avg_severity']}")
            print(f"   Worst Event: {summary['worst_severity']}")
            print(f"   Unique Actors: {summary['unique_actors']}")
            print(f"   Media Coverage: {summary['total_coverage']} articles")
            print(f"   Most Recent: {summary['most_recent']}")


def test_trending():
    """Test 3: High-coverage trending threats"""
    print("\n" + "="*70)
    print("TEST 3: Trending Threats (High Media Coverage)")
    print("="*70)
    
    trending = GDELTQuery.get_trending_threats(days=7, min_articles=10)
    
    if trending:
        print(f"\nFound {len(trending)} highly-covered conflict events (last 7 days):\n")
        
        for i, t in enumerate(trending[:10], 1):
            country = f"({t['country']})" if t['country'] else ""
            print(f"{i:2d}. {t['date']} {country}")
            print(f"    {t['actor1']} → {t['actor2']}")
            print(f"    📰 {t['articles']} articles, {t['sources']} sources")
            print(f"    🔥 Severity: {t['severity']}")
            if t['source_url']:
                print(f"    🔗 {t['source_url'][:60]}...")
            print()
    else:
        print("\n⚠ No trending threats found. Try lowering min_articles parameter.")


def test_api_usage():
    """Test 4: Show example API usage"""
    print("\n" + "="*70)
    print("TEST 4: API Endpoint Usage Examples")
    print("="*70)
    
    print("""
The following endpoints are now available:

1. GET /api/gdelt/threats/nearby
   Parameters: lat, lon, radius (default 50km), days (default 7)
   Example: /api/gdelt/threats/nearby?lat=50.45&lon=30.52&radius=100&days=7
   
2. GET /api/gdelt/country/<code>
   Parameters: days (default 30)
   Example: /api/gdelt/country/UA?days=30
   
3. GET /api/gdelt/trending
   Parameters: days (default 7), min_articles (default 10)
   Example: /api/gdelt/trending?days=7&min_articles=5

4. GET /admin/gdelt/health
   No parameters - returns polling status and metrics

5. POST /admin/gdelt/ingest
   Requires: X-API-Key header
   Manually trigger ingestion
""")


def main():
    print("\n" + "🚀 GDELT HYBRID SYSTEM TEST".center(70, "="))
    print("Production ingestion + High-performance query layer".center(70))
    
    try:
        test_location_query()
        test_country_summaries()
        test_trending()
        test_api_usage()
        
        print("\n" + "="*70)
        print("✅ ALL TESTS COMPLETE")
        print("="*70)
        print("\nNext steps:")
        print("  1. Deploy to Railway (GDELT_ENABLED=true)")
        print("  2. Wait 15-30 minutes for first ingestion cycle")
        print("  3. Query via API endpoints above")
        print("  4. Monitor via /admin/gdelt/health")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
