#!/usr/bin/env python3
"""
Comprehensive test for buffer cleanup functionality.
Tests multiple scenarios including concurrent access and various error conditions.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import threading
import time
import unittest.mock
from rss_processor import (
    ingest_all_feeds_to_db, _LOCATION_BATCH_BUFFER, _LOCATION_BATCH_LOCK
)

async def test_concurrent_buffer_access():
    """Test that buffer cleanup works correctly with concurrent access"""
    
    print("=== Testing Concurrent Buffer Access ===\n")
    
    # Add initial entries
    with _LOCATION_BATCH_LOCK:
        _LOCATION_BATCH_BUFFER.extend([
            ({"title": "Concurrent Test 1", "summary": "Test"}, "global", "test-uuid-c1"),
            ({"title": "Concurrent Test 2", "summary": "Test"}, "global", "test-uuid-c2")
        ])
        buffer_size_before = len(_LOCATION_BATCH_BUFFER)
    
    print(f"🔧 Initial buffer size: {buffer_size_before}")
    
    # Function to add more entries while ingestion is running
    def background_buffer_modifier():
        time.sleep(0.1)  # Small delay to ensure ingestion starts first
        with _LOCATION_BATCH_LOCK:
            _LOCATION_BATCH_BUFFER.append(
                ({"title": "Background Entry", "summary": "Test"}, "global", "test-uuid-bg")
            )
            print("🔧 Background thread added 1 entry to buffer")
    
    # Start background thread
    bg_thread = threading.Thread(target=background_buffer_modifier)
    bg_thread.start()
    
    # Mock to ensure no real HTTP requests and add a small delay
    async def mock_ingest_feeds(specs, limit):
        await asyncio.sleep(0.2)  # Give background thread time to run
        return []
    
    with unittest.mock.patch('rss_processor._coalesce_all_feed_specs', return_value=[]):
        with unittest.mock.patch('rss_processor.ingest_feeds', side_effect=mock_ingest_feeds):
            try:
                result = await ingest_all_feeds_to_db(
                    group_names=[], 
                    limit=10, 
                    write_to_db=False
                )
                print(f"✅ Ingestion completed: {result['count']} alerts")
                
            except Exception as e:
                print(f"⚠️  Exception occurred: {e}")
    
    bg_thread.join()  # Wait for background thread to complete
    
    # Check final buffer state
    with _LOCATION_BATCH_LOCK:
        buffer_size_after = len(_LOCATION_BATCH_BUFFER)
    
    print(f"📊 Buffer state check:")
    print(f"   Final size: {buffer_size_after} entries")
    
    success = buffer_size_after == 0
    if success:
        print("✅ Buffer successfully cleaned up despite concurrent access!")
    else:
        print("❌ Buffer cleanup failed with concurrent access!")
    
    return success

async def test_buffer_cleanup_multiple_calls():
    """Test that buffer cleanup works across multiple consecutive calls"""
    
    print("\n=== Testing Multiple Consecutive Calls ===\n")
    
    all_success = True
    
    for i in range(3):
        print(f"🔄 Test iteration {i+1}")
        
        # Add entries to buffer
        with _LOCATION_BATCH_LOCK:
            _LOCATION_BATCH_BUFFER.extend([
                ({"title": f"Multi Test {i}-{j}", "summary": "Test"}, "global", f"test-uuid-m{i}-{j}")
                for j in range(2)
            ])
            buffer_size_before = len(_LOCATION_BATCH_BUFFER)
        
        print(f"   Added {buffer_size_before} entries to buffer")
        
        with unittest.mock.patch('rss_processor._coalesce_all_feed_specs', return_value=[]):
            try:
                result = await ingest_all_feeds_to_db(
                    group_names=[], 
                    limit=10, 
                    write_to_db=False
                )
                
            except Exception as e:
                print(f"   Exception: {e}")
        
        # Check buffer state
        with _LOCATION_BATCH_LOCK:
            buffer_size_after = len(_LOCATION_BATCH_BUFFER)
        
        iteration_success = buffer_size_after == 0
        if iteration_success:
            print(f"   ✅ Iteration {i+1} buffer cleaned successfully")
        else:
            print(f"   ❌ Iteration {i+1} buffer cleanup failed")
            all_success = False
    
    return all_success

async def test_buffer_empty_state():
    """Test behavior when buffer is already empty"""
    
    print("\n=== Testing Empty Buffer State ===\n")
    
    # Ensure buffer is empty
    with _LOCATION_BATCH_LOCK:
        _LOCATION_BATCH_BUFFER.clear()
        buffer_size_before = len(_LOCATION_BATCH_BUFFER)
    
    print(f"🔧 Buffer size before: {buffer_size_before}")
    
    with unittest.mock.patch('rss_processor._coalesce_all_feed_specs', return_value=[]):
        try:
            result = await ingest_all_feeds_to_db(
                group_names=[], 
                limit=10, 
                write_to_db=False
            )
            print(f"✅ Ingestion completed with empty buffer: {result['count']} alerts")
            
        except Exception as e:
            print(f"⚠️  Exception occurred: {e}")
    
    # Check buffer state
    with _LOCATION_BATCH_LOCK:
        buffer_size_after = len(_LOCATION_BATCH_BUFFER)
    
    success = buffer_size_after == 0
    if success:
        print("✅ Empty buffer handling successful!")
    else:
        print("❌ Empty buffer handling failed!")
    
    return success

if __name__ == "__main__":
    async def run_comprehensive_tests():
        print("🧪 Running Comprehensive Buffer Cleanup Tests\n")
        
        # Test concurrent access
        success1 = await test_concurrent_buffer_access()
        
        # Test multiple calls
        success2 = await test_buffer_cleanup_multiple_calls()
        
        # Test empty buffer
        success3 = await test_buffer_empty_state()
        
        overall_success = success1 and success2 and success3
        
        print(f"\n📊 Test Summary:")
        print(f"   Concurrent access: {'✅ PASSED' if success1 else '❌ FAILED'}")
        print(f"   Multiple calls:    {'✅ PASSED' if success2 else '❌ FAILED'}")
        print(f"   Empty buffer:      {'✅ PASSED' if success3 else '❌ FAILED'}")
        print(f"\n🎯 Overall Result: {'✅ ALL TESTS PASSED' if overall_success else '❌ SOME TESTS FAILED'}")
        
        return overall_success
    
    success = asyncio.run(run_comprehensive_tests())
