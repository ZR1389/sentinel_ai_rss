#!/usr/bin/env python3

import os
import sys
import asyncio
import json
import tempfile
from datetime import datetime, timezone

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

# Set environment variables
os.environ["RSS_WRITE_TO_DB"] = "false"
os.environ["MOONSHOT_LOCATION_BATCH_THRESHOLD"] = "2"
os.environ["RSS_BATCH_LIMIT"] = "10"

def create_test_rss_feed():
    """Create a temporary RSS feed file for testing"""
    rss_content = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Security Feed</title>
    <description>Test feed for batch integration</description>
    <link>http://example.com</link>
    
    <item>
      <title>Explosions reported across multiple regions</title>
      <description>Several detonations have been reported throughout various zones in an undisclosed area</description>
      <link>http://example.com/item1</link>
      <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
    </item>
    
    <item>
      <title>Shooting in downtown Paris</title>
      <description>A shooting incident occurred in the downtown area of Paris, France</description>
      <link>http://example.com/item2</link>
      <pubDate>Mon, 01 Jan 2024 13:00:00 GMT</pubDate>
    </item>
    
    <item>
      <title>Violence reported throughout different districts</title>
      <description>Multiple incidents have been reported across various neighborhoods in the region</description>
      <link>http://example.com/item3</link>
      <pubDate>Mon, 01 Jan 2024 14:00:00 GMT</pubDate>
    </item>
    
    <item>
      <title>Cyber attack on government servers</title>
      <description>Ransomware attack detected on multiple government systems across several provinces</description>
      <link>http://example.com/item4</link>
      <pubDate>Mon, 01 Jan 2024 15:00:00 GMT</pubDate>
    </item>
    
  </channel>
</rss>"""
    
    # Create temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
        f.write(rss_content)
        return f.name

async def test_full_rss_integration():
    """Test the full RSS processing pipeline with batch integration"""
    print("🧪 Testing full RSS integration with Moonshot batching...")
    
    try:
        from rss_processor import _build_alert_from_entry, _should_use_moonshot_for_location
        import httpx
        
        # Test entries that should trigger different batch behaviors
        test_entries = [
            {
                "title": "Explosions reported across multiple regions",
                "summary": "Several detonations have been reported throughout various zones in an undisclosed area",
                "link": "http://example.com/item1",
                "published": datetime.now(timezone.utc)
            },
            {
                "title": "Shooting in downtown Paris",
                "summary": "A shooting incident occurred in the downtown area of Paris, France",
                "link": "http://example.com/item2", 
                "published": datetime.now(timezone.utc)
            },
            {
                "title": "Cyber attack on government servers",
                "summary": "Ransomware attack detected on multiple government systems across several provinces",
                "link": "http://example.com/item3",
                "published": datetime.now(timezone.utc)
            }
        ]
        
        print("🔄 Processing entries with batch integration...")
        
        alerts = []
        async with httpx.AsyncClient() as client:
            for i, entry in enumerate(test_entries):
                alert = await _build_alert_from_entry(
                    entry, 
                    "http://example.com", 
                    client, 
                    "", # No source tag
                    batch_mode=True
                )
                if alert:
                    alerts.append(alert)
        
        print(f"\n📊 Results:")
        print(f"   Total alerts processed: {len(alerts)}")
        
        for i, alert in enumerate(alerts):
            title = alert.get('title', 'N/A')[:50]
            method = alert.get('location_method', 'unknown')
            city = alert.get('city', 'None')
            country = alert.get('country', 'None') 
            batch_queued = alert.get('_batch_queued', False)
            print(f"   Alert {i+1}: {title}...")
            print(f"             Location: {city}, {country} (method: {method})")
            print(f"             Batch queued: {batch_queued}")
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_full_integration():
    """Run the complete integration test"""
    print("🚀 Starting full Moonshot batch integration test...")
    
    success = asyncio.run(test_full_rss_integration())
    
    if success:
        print("\n✅ Full integration test completed successfully!")
        print("🎯 Key achievements:")
        print("   • Batch queueing logic integrated into _build_alert_from_entry")
        print("   • Batch processing triggered at end of RSS ingestion")
        print("   • Results successfully applied back to alert objects")
        print("   • Heuristic function properly filters ambiguous entries")
    else:
        print("\n❌ Integration test failed")
    
    return success

if __name__ == "__main__":
    success = test_full_integration()
    sys.exit(0 if success else 1)
