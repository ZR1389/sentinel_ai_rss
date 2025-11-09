#!/usr/bin/env python3
"""
Test the enhanced Moonshot batching with better location service and async processing.
"""
import asyncio
import httpx
from rss_processor import (
    _build_alert_from_entry, _LOCATION_BATCH_BUFFER, _LOCATION_BATCH_LOCK,
    _should_use_moonshot_for_location, _process_location_batch,
    _apply_moonshot_locations
)

async def test_enhanced_batching():
    """Test the enhanced async Moonshot batching system"""
    
    print("=== Testing Enhanced Moonshot Batching ===\n")
    
    # Test entries designed to pass keyword filter AND test location detection
    test_entries = [
        {
            "title": "PARIS: Shooting near government building",  # Should pass keyword filter + deterministic location
            "summary": "Police respond to shooting incident near government offices in central Paris. Multiple emergency vehicles deployed.",
            "link": "http://example.com/1",
            "published": None,
        },
        {
            "title": "Government security alert in major city",  # Should pass filter but need Moonshot for location
            "summary": "Authorities investigate suspicious activity downtown. Police cordoned off several blocks as precaution.",
            "link": "http://example.com/2", 
            "published": None,
        },
        {
            "title": "LONDON: Cyber attack targets government systems",  # Should pass + deterministic location
            "summary": "Critical infrastructure hit by ransomware. Government agencies coordinating response to widespread breach.",
            "link": "http://example.com/3",
            "published": None,
        },
        {
            "title": "Regional authorities respond to cyber incident",  # Should pass filter but ambiguous location
            "summary": "Government officials investigate data breach affecting multiple facilities. Cybersecurity teams deployed nationwide.",
            "link": "http://example.com/4",
            "published": None,
        }
    ]
    
    # Clear batch buffer 
    with _LOCATION_BATCH_LOCK:
        _LOCATION_BATCH_BUFFER.clear()
    
    print("🔍 Testing Entry Qualification:")
    for i, entry in enumerate(test_entries, 1):
        should_use = _should_use_moonshot_for_location(entry, "")
        print(f"  Entry {i}: \"{entry['title'][:50]}...\"")
        print(f"    Moonshot needed: {should_use}")
    
    print("\n🚀 Testing Async Alert Building:")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        alerts = []
        
        for i, entry in enumerate(test_entries, 1):
            print(f"\n  Processing Entry {i}: \"{entry['title'][:50]}...\"")
            
            try:
                # Build alert with batch_mode=True
                alert = await _build_alert_from_entry(
                    entry, "http://example.com", client, 
                    source_tag="global", batch_mode=True
                )
                
                if alert:
                    alerts.append(alert)
                    print(f"    ✅ Alert created: {alert.get('city', 'None')}, {alert.get('country', 'None')}")
                    print(f"       Method: {alert.get('location_method', 'None')}, Confidence: {alert.get('location_confidence', 'None')}")
                    if alert.get('_batch_queued'):
                        print(f"       🧠 Queued for Moonshot batch processing")
                else:
                    print(f"    ❌ Alert filtered out (likely keyword filter)")
                    
            except Exception as e:
                print(f"    ⚠️  Error: {e}")
    
        print(f"\n📊 Processing Results:")
        print(f"   Created alerts: {len(alerts)}")
        
        # Check batch buffer state
        with _LOCATION_BATCH_LOCK:
            buffer_size = len(_LOCATION_BATCH_BUFFER)
        
        print(f"   Batch buffer size: {buffer_size}")
        
        if buffer_size > 0:
            print(f"\n🧠 Processing final Moonshot batch...")
            try:
                batch_results = await _process_location_batch(client)
                print(f"   ✅ Async batch processed: {len(batch_results)} results")
                
                # Apply batch results
                if batch_results:
                    _apply_moonshot_locations(alerts, batch_results)
                    print(f"   📍 Applied batch results to alerts")
                    
            except Exception as e:
                print(f"   ⚠️  Batch processing error: {e}")
    
    print(f"\n📈 Final Summary: {len(alerts)} alerts processed")
    return alerts

if __name__ == "__main__":
    alerts = asyncio.run(test_enhanced_batching())
    
    print("\n" + "="*60)
    print("📋 Final Alert Results:")
    for i, alert in enumerate(alerts, 1):
        print(f"{i}. {alert['title'][:60]}...")
        print(f"   Location: {alert.get('city', 'None')}, {alert.get('country', 'None')}")
        print(f"   Method: {alert.get('location_method', 'None')} (confidence: {alert.get('location_confidence', 'None')})")
        print(f"   UUID: {alert['uuid'][:8]}")
        print(f"   Batch queued: {alert.get('_batch_queued', False)}")
        print()
