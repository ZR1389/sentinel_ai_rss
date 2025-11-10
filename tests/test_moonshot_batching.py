#!/usr/bin/env python3
"""
Test script for Moonshot hybrid batching system
"""

import os
import sys
sys.path.append('.')

from dotenv import load_dotenv
load_dotenv()

from rss_processor import (
    _LOCATION_BATCH_BUFFER, 
    _LOCATION_BATCH_LOCK,
    _should_use_moonshot_for_location,
    _process_location_batch
)

def test_moonshot_batching():
    """Test the hybrid batching system"""
    async def run_test():
        print("🧪 Testing Moonshot Hybrid Batching System\n")
        
        # Test entries that should trigger batching
        test_entries = [
        {
            'title': 'Multiple cyber incidents reported across European region',
            'summary': 'Various countries affected by coordinated attacks',
            'uuid': 'test-001'
        },
        {
            'title': 'Security threats throughout Asia-Pacific area',
            'summary': 'Several nations experiencing disruptions',
            'uuid': 'test-002'
        },
        {
            'title': 'Ransomware hits Paris hospital',
            'summary': 'Clear location incident',
            'uuid': 'test-003'
        }
    ]
    
    # Test heuristics
    print("1️⃣ Testing location heuristics:")
    for i, entry in enumerate(test_entries):
        should_batch = _should_use_moonshot_for_location(entry, f"test-tag-{i}")
        print(f"   Entry {i+1}: {'🎯 BATCH' if should_batch else '⚡ FAST'} - {entry['title'][:50]}...")
    
    print("\n2️⃣ Testing batch buffer:")
    with _LOCATION_BATCH_LOCK:
        # Clear any existing buffer
        _LOCATION_BATCH_BUFFER.clear()
        
        # Add ambiguous entries to batch
        for i, entry in enumerate(test_entries[:2]):  # First 2 are ambiguous
            if _should_use_moonshot_for_location(entry, f"test-tag-{i}"):
                _LOCATION_BATCH_BUFFER.append((entry, f"test-tag-{i}", entry['uuid']))
        
        print(f"   Buffer size: {len(_LOCATION_BATCH_BUFFER)} entries")
    
    print("\n3️⃣ Testing batch processing:")
    if _LOCATION_BATCH_BUFFER:
        try:
            results = _process_location_batch_sync()
            print(f"   Processed: {len(results)} location results")
            for uuid, data in results.items():
                city = data.get('city', 'N/A')
                country = data.get('country', 'N/A')
                method = data.get('location_method', 'N/A')
                print(f"   {uuid}: {city}, {country} ({method})")
        except Exception as e:
            print(f"   ⚠️  Batch processing failed (expected if no API key): {e}")
    
    print("\n✅ Hybrid batching system test complete!")
    print(f"💰 Efficiency: Only {len([e for e in test_entries if _should_use_moonshot_for_location(e, 'test')])}/{len(test_entries)} entries would use LLM")

if __name__ == "__main__":
    test_moonshot_batching()
