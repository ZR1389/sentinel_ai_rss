#!/usr/bin/env python3
"""
Test race condition fixes in batch processing.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import threading
import time
import unittest.mock
from rss_processor import (
    _LOCATION_BATCH_BUFFER, _LOCATION_BATCH_LOCK,
    _PENDING_BATCH_RESULTS, _PENDING_BATCH_RESULTS_LOCK,
    _process_location_batch_sync
)

def test_thread_safe_pending_results():
    """Test that pending batch results storage is thread-safe"""
    
    print("=== Testing Thread-Safe Pending Results Storage ===\n")
    
    # Clear any existing state
    with _PENDING_BATCH_RESULTS_LOCK:
        _PENDING_BATCH_RESULTS.clear()
    
    results_from_threads = []
    exceptions = []
    
    def worker_thread(thread_id: int):
        """Simulate multiple threads accessing pending results"""
        try:
            # Add some results
            test_results = {
                f"uuid-{thread_id}-{i}": {
                    'city': f'City{thread_id}', 
                    'country': f'Country{thread_id}',
                    'location_method': 'moonshot_batch'
                }
                for i in range(5)
            }
            
            with _PENDING_BATCH_RESULTS_LOCK:
                _PENDING_BATCH_RESULTS.update(test_results)
                time.sleep(0.01)  # Simulate some work
                current_size = len(_PENDING_BATCH_RESULTS)
                results_from_threads.append(current_size)
                
        except Exception as e:
            exceptions.append(f"Thread {thread_id}: {e}")
    
    # Start multiple threads
    threads = []
    for i in range(5):
        t = threading.Thread(target=worker_thread, args=(i,))
        threads.append(t)
        t.start()
    
    # Wait for all threads
    for t in threads:
        t.join()
    
    # Check results
    with _PENDING_BATCH_RESULTS_LOCK:
        final_size = len(_PENDING_BATCH_RESULTS)
        _PENDING_BATCH_RESULTS.clear()
    
    print(f"🔧 Started 5 threads adding results")
    print(f"📊 Final pending results size: {final_size}")
    print(f"⚠️  Exceptions encountered: {len(exceptions)}")
    
    if exceptions:
        for exc in exceptions:
            print(f"   {exc}")
    
    success = len(exceptions) == 0 and final_size == 25  # 5 threads × 5 results each
    if success:
        print("✅ Thread-safe pending results storage works correctly!")
    else:
        print("❌ Thread-safe pending results storage failed!")
    
    return success

def test_batch_error_recovery():
    """Test that batch buffer is preserved on processing errors"""
    
    print("\n=== Testing Batch Error Recovery ===\n")
    
    # Clear buffers
    with _LOCATION_BATCH_LOCK:
        _LOCATION_BATCH_BUFFER.clear()
    
    # Add test entries
    test_entries = [
        ({"title": "Test Entry 1", "summary": "Test"}, "global", "test-uuid-1"),
        ({"title": "Test Entry 2", "summary": "Test"}, "global", "test-uuid-2")
    ]
    
    with _LOCATION_BATCH_LOCK:
        _LOCATION_BATCH_BUFFER.extend(test_entries)
        buffer_size_before = len(_LOCATION_BATCH_BUFFER)
    
    print(f"🔧 Added {buffer_size_before} entries to buffer")
    
    # Mock moonshot_chat to raise an exception
    with unittest.mock.patch('moonshot_client.moonshot_chat', side_effect=Exception("Simulated API error")):
        # This should fail but preserve buffer
        result = _process_location_batch_sync()
    
    # Check that buffer was NOT cleared due to error
    with _LOCATION_BATCH_LOCK:
        buffer_size_after_error = len(_LOCATION_BATCH_BUFFER)
    
    print(f"📊 Buffer state after error:")
    print(f"   Before: {buffer_size_before} entries")
    print(f"   After error: {buffer_size_after_error} entries")
    print(f"   Result: {result}")
    
    # Now test successful processing clears buffer
    with unittest.mock.patch('moonshot_client.moonshot_chat', return_value='[{"alert_uuid": "test-uuid-1", "city": "TestCity", "country": "TestCountry"}]'):
        result = _process_location_batch_sync()
    
    with _LOCATION_BATCH_LOCK:
        buffer_size_after_success = len(_LOCATION_BATCH_BUFFER)
    
    print(f"   After success: {buffer_size_after_success} entries")
    
    success = (
        buffer_size_after_error == buffer_size_before and  # Error preserves buffer
        buffer_size_after_success == 0 and                # Success clears buffer
        len(result) > 0                                    # Success returns results
    )
    
    if success:
        print("✅ Batch error recovery works correctly!")
    else:
        print("❌ Batch error recovery failed!")
    
    return success

def test_no_function_attribute_pollution():
    """Test that we no longer pollute function objects with attributes"""
    
    print("\n=== Testing No Function Attribute Pollution ===\n")
    
    # Import the function
    from rss_processor import _build_alert_from_entry
    
    # Check that the function doesn't have the problematic attribute
    has_pending_results = hasattr(_build_alert_from_entry, '_pending_batch_results')
    
    print(f"🔧 Checking _build_alert_from_entry for _pending_batch_results attribute")
    print(f"📊 Function has _pending_batch_results attribute: {has_pending_results}")
    
    if not has_pending_results:
        print("✅ No function attribute pollution!")
        return True
    else:
        print("❌ Function still has problematic attribute!")
        return False

if __name__ == "__main__":
    async def run_race_condition_tests():
        print("🧪 Running Race Condition Fix Tests\n")
        
        # Test thread-safe pending results
        success1 = test_thread_safe_pending_results()
        
        # Test batch error recovery
        success2 = test_batch_error_recovery()
        
        # Test no function attribute pollution
        success3 = test_no_function_attribute_pollution()
        
        overall_success = success1 and success2 and success3
        
        print(f"\n📊 Test Summary:")
        print(f"   Thread-safe storage:     {'✅ PASSED' if success1 else '❌ FAILED'}")
        print(f"   Batch error recovery:    {'✅ PASSED' if success2 else '❌ FAILED'}")
        print(f"   No function pollution:   {'✅ PASSED' if success3 else '❌ FAILED'}")
        print(f"\n🎯 Overall Result: {'✅ ALL TESTS PASSED' if overall_success else '❌ SOME TESTS FAILED'}")
        
        return overall_success
    
    success = asyncio.run(run_race_condition_tests())
