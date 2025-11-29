#!/usr/bin/env python3
"""
Test buffer cleanup functionality with simulated error.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import unittest.mock
from services.rss_processor import (
    ingest_all_feeds_to_db, _LOCATION_BATCH_BUFFER, _LOCATION_BATCH_LOCK
)

async def test_buffer_cleanup():
    """Test that buffer gets cleared even on errors"""
    
    print("=== Testing Buffer Cleanup with Error Simulation ===\n")
    
    # Manually add something to buffer to simulate leftover state
    with _LOCATION_BATCH_LOCK:
        _LOCATION_BATCH_BUFFER.extend([
            ({"title": "Test Entry", "summary": "Test"}, "global", "test-uuid-1"),
            ({"title": "Another Test", "summary": "Test"}, "global", "test-uuid-2")
        ])
        buffer_size_before = len(_LOCATION_BATCH_BUFFER)
    
    print(f"🔧 Manually added {buffer_size_before} entries to buffer")
    
    # Mock the feed loading to return empty list to avoid HTTP requests
    with unittest.mock.patch('rss_processor._coalesce_all_feed_specs', return_value=[]):
        try:
            # Try to run ingestion (will have no feeds but should still clean buffer)
            result = await ingest_all_feeds_to_db(
                group_names=[], 
                limit=10, 
                write_to_db=False  # Don't actually write to DB
            )
            
            print(f"✅ Ingestion completed: {result['count']} alerts")
            
        except Exception as e:
            print(f"⚠️  Exception occurred (expected): {e}")
    
    # Check if buffer was cleaned
    with _LOCATION_BATCH_LOCK:
        buffer_size_after = len(_LOCATION_BATCH_BUFFER)
    
    print(f"📊 Buffer state check:")
    print(f"   Before: {buffer_size_before} entries")
    print(f"   After:  {buffer_size_after} entries")
    
    if buffer_size_after == 0:
        print("✅ Buffer successfully cleaned up!")
    else:
        print("❌ Buffer cleanup failed!")
    
    return buffer_size_after == 0

async def test_buffer_cleanup_with_exception():
    """Test buffer cleanup when an exception occurs during processing"""
    
    print("\n=== Testing Buffer Cleanup with Exception ===\n")
    
    # Add entries to buffer
    with _LOCATION_BATCH_LOCK:
        _LOCATION_BATCH_BUFFER.extend([
            ({"title": "Exception Test", "summary": "Test"}, "global", "test-uuid-3")
        ])
        buffer_size_before = len(_LOCATION_BATCH_BUFFER)
    
    print(f"🔧 Manually added {buffer_size_before} entries to buffer")
    
    # Mock feed loading to return empty list and ingest_feeds to raise an exception
    with unittest.mock.patch('rss_processor._coalesce_all_feed_specs', return_value=[]):
        with unittest.mock.patch('rss_processor.ingest_feeds', side_effect=Exception("Simulated error")):
            try:
                result = await ingest_all_feeds_to_db(
                    group_names=[], 
                    limit=10, 
                    write_to_db=False
                )
                print(f"✅ Unexpected success: {result}")
            except Exception as e:
                print(f"⚠️  Exception occurred as expected: {e}")
    
    # Check if buffer was cleaned even with exception
    with _LOCATION_BATCH_LOCK:
        buffer_size_after = len(_LOCATION_BATCH_BUFFER)
    
    print(f"📊 Buffer state check:")
    print(f"   Before: {buffer_size_before} entries")
    print(f"   After:  {buffer_size_after} entries")
    
    if buffer_size_after == 0:
        print("✅ Buffer successfully cleaned up even with exception!")
    else:
        print("❌ Buffer cleanup failed with exception!")
    
    return buffer_size_after == 0

if __name__ == "__main__":
    async def run_all_tests():
        # Test normal cleanup
        success1 = await test_buffer_cleanup()
        
        # Test cleanup with exception
        success2 = await test_buffer_cleanup_with_exception()
        
        overall_success = success1 and success2
        print(f"\n🎯 Overall Test Result: {'PASSED' if overall_success else 'FAILED'}")
        return overall_success
    
    success = asyncio.run(run_all_tests())
