#!/usr/bin/env python3
"""
Final integration test of Moonshot batching with improved location service.
"""
import asyncio
import httpx
import json
from rss_processor import (
    _build_alert_from_entry, _LOCATION_BATCH_BUFFER, _LOCATION_BATCH_LOCK,
    _should_use_moonshot_for_location, _process_location_batch
)

async def test_location_detection():
    """Test the full location detection pipeline"""
    
    print("=== Testing Full Location Detection Pipeline ===\n")
    
    # Test entries with varying location clarity
    test_entries = [
        {
            "title": "Shooting in Paris, France",
            "summary": "Police investigate incident near Eiffel Tower",
            "link": "http://example.com/1",
            "published": None,
        },
        {
            "title": "Local authorities respond to emergency",
            "summary": "Police and emergency services called to downtown area after reports of suspicious activity",
            "link": "http://example.com/2", 
            "published": None,
        },
        {
            "title": "LONDON: Security alert at airport",
            "summary": "Heathrow terminals temporarily evacuated as precaution",
            "link": "http://example.com/3",
            "published": None,
        },
        {
            "title": "Cybersecurity breach reported",
            "summary": "Government officials investigate data compromise at multiple facilities in the region",
            "link": "http://example.com/4",
            "published": None,
        },
        {
            "title": "Tokyo police arrest suspects", 
            "summary": "Multiple individuals detained in connection with organized crime",
            "link": "http://example.com/5",
            "published": None,
        }
    ]
    
    # Test Moonshot qualification
    print("🔍 Testing Moonshot Qualification:")
    for i, entry in enumerate(test_entries, 1):
        should_use = _should_use_moonshot_for_location(entry, "")
        print(f"  Entry {i}: \"{entry['title'][:50]}...\"")
        print(f"    Moonshot needed: {should_use}")
    
    print()
    
    # Test batch processing with async client
    print("🚀 Testing Alert Building (simulated):")
    
    # Clear batch buffer 
    with _LOCATION_BATCH_LOCK:
        _LOCATION_BATCH_BUFFER.clear()
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        alerts = []
        
        for i, entry in enumerate(test_entries, 1):
            print(f"  Processing Entry {i}: \"{entry['title'][:50]}...\"")
            
            try:
                # Build alert (with batch_mode=True to enable batching)
                alert = await _build_alert_from_entry(
                    entry, "http://example.com", client, 
                    source_tag="", batch_mode=True
                )
                
                if alert:
                    alerts.append(alert)
                    print(f"    ✅ Alert created: {alert.get('city', 'None')}, {alert.get('country', 'None')}")
                    print(f"       Method: {alert.get('location_method', 'None')}, Confidence: {alert.get('location_confidence', 'None')}")
                else:
                    print(f"    ❌ Alert filtered out")
                    
            except Exception as e:
                print(f"    ⚠️  Error: {e}")
    
    print()
    
    # Check batch buffer state
    with _LOCATION_BATCH_LOCK:
        buffer_size = len(_LOCATION_BATCH_BUFFER)
    
    print(f"📊 Batch Buffer State: {buffer_size} entries queued")
    
    if buffer_size > 0:
        print("🧠 Processing Moonshot batch...")
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                batch_results = await _process_location_batch(client)
            print(f"   ✅ Batch processed: {len(batch_results)} results")
            for uuid, location in batch_results.items():
                print(f"      {uuid[:8]}: {location.get('city', 'None')}, {location.get('country', 'None')}")
        except Exception as e:
            print(f"   ⚠️  Batch processing error: {e}")
    
    print()
    print(f"📈 Summary: {len(alerts)} alerts created from {len(test_entries)} entries")
    return alerts

if __name__ == "__main__":
    alerts = asyncio.run(test_location_detection())
    
    print("\n" + "="*60)
    print("📋 Final Alert Summary:")
    for i, alert in enumerate(alerts, 1):
        print(f"{i}. {alert['title'][:60]}...")
        print(f"   Location: {alert.get('city', 'None')}, {alert.get('country', 'None')}")
        print(f"   Method: {alert.get('location_method', 'None')} (confidence: {alert.get('location_confidence', 'None')})")
        print(f"   UUID: {alert['uuid'][:8]}")
