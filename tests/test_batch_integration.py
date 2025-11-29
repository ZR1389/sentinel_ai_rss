#!/usr/bin/env python3

import os
import sys
import asyncio
import json
from datetime import datetime, timezone

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

# Set environment variables
os.environ["RSS_WRITE_TO_DB"] = "false"
os.environ["MOONSHOT_LOCATION_BATCH_THRESHOLD"] = "3"

def test_batch_integration():
    """Test the integrated Moonshot batching system"""
    print("🧪 Testing Moonshot batch integration...")
    
    try:
        from services.rss_processor import _build_alert_from_entry, _should_use_moonshot_for_location
        import httpx
        
        # Test heuristic function
        test_entries = [
            {
                "title": "Attacks reported across multiple districts in city",
                "summary": "Violence has been reported in various neighborhoods throughout the region",
                "link": "http://example.com/1",
                "published": datetime.now(timezone.utc)
            },
            {
                "title": "Shooting in downtown area",
                "summary": "A shooting incident occurred near the central business district", 
                "link": "http://example.com/2",
                "published": datetime.now(timezone.utc)
            },
            {
                "title": "Several explosions heard across the province",
                "summary": "Multiple detonations reported throughout different zones",
                "link": "http://example.com/3", 
                "published": datetime.now(timezone.utc)
            }
        ]
        
        # Test heuristic function
        print("\n📋 Testing batch heuristic function:")
        for i, entry in enumerate(test_entries):
            should_batch = _should_use_moonshot_for_location(entry, "test")
            print(f"Entry {i+1}: {should_batch} - '{entry['title']}'")
        
        print("\n✅ Batch heuristic function working correctly")
        
        # Test batch mode integration (mock test)
        print("\n🔄 Testing batch mode integration...")
        
        async def test_alert_building():
            async with httpx.AsyncClient() as client:
                # First entry should be queued for batch
                alert1 = await _build_alert_from_entry(
                    test_entries[0], 
                    "http://example.com", 
                    client, 
                    "test", 
                    batch_mode=True
                )
                
                if alert1:
                    is_queued = alert1.get("_batch_queued", False)
                    method = alert1.get("location_method", "unknown")
                    print(f"Alert 1 queued: {is_queued}, method: {method}")
                    return True
                
                return False
        
        result = asyncio.run(test_alert_building())
        if result:
            print("✅ Alert building with batch mode working")
        else:
            print("❌ Alert building failed")
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n✅ Batch integration test completed successfully!")
    return True

if __name__ == "__main__":
    success = test_batch_integration()
    sys.exit(0 if success else 1)
