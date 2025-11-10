#!/usr/bin/env python3
"""
Memory Leak Prevention Test for Moonshot Location Batching

This script tests the memory leak fixes implemented for:
1. Alerts marked with _batch_queued=True that never get processed
2. _LOCATION_BATCH_BUFFER growing unbounded if processing repeatedly fails
3. Stale _PENDING_BATCH_RESULTS accumulating

Test scenarios:
- Buffer size limit enforcement
- Age-based cleanup of stale items
- Retry limit handling for failed batches
- Cleanup of stale batch markers from alerts
"""

import sys
import os
import time
import asyncio
import threading
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

# Add the parent directory to the path to import rss_processor
sys.path.insert(0, '/Users/zikarakita/Documents/sentinel_ai_rss')

import rss_processor

def test_buffer_size_limit():
    """Test that buffer size limit is enforced"""
    print("Testing buffer size limit enforcement...")
    
    # Clear existing buffer
    with rss_processor._LOCATION_BATCH_LOCK:
        rss_processor._LOCATION_BATCH_BUFFER.clear()
        rss_processor._BUFFER_TIMESTAMPS.clear()
    
    # Set a small buffer size for testing
    original_max_size = rss_processor.MAX_BUFFER_SIZE
    rss_processor.MAX_BUFFER_SIZE = 5
    
    try:
        # Add more items than the limit
        current_time = time.time()
        for i in range(10):
            alert = {'uuid': f'test-uuid-{i}', 'title': f'Test Alert {i}'}
            uuid = alert['uuid']
            
            with rss_processor._LOCATION_BATCH_LOCK:
                rss_processor._LOCATION_BATCH_BUFFER.append((alert, 'test-tag', uuid))
                rss_processor._BUFFER_TIMESTAMPS[uuid] = current_time + i  # Higher index = newer timestamp
        
        print(f"Added 10 items to buffer, current size: {len(rss_processor._LOCATION_BATCH_BUFFER)}")
        
        # Trigger size limit enforcement
        removed = rss_processor._enforce_buffer_size_limit()
        print(f"Removed {removed} items due to size limit")
        
        # Verify buffer size is within limits
        with rss_processor._LOCATION_BATCH_LOCK:
            final_size = len(rss_processor._LOCATION_BATCH_BUFFER)
            timestamp_count = len(rss_processor._BUFFER_TIMESTAMPS)
        
        print(f"Final buffer size: {final_size}, timestamp count: {timestamp_count}")
        
        assert final_size <= rss_processor.MAX_BUFFER_SIZE, f"Buffer size {final_size} exceeds limit {rss_processor.MAX_BUFFER_SIZE}"
        assert timestamp_count == final_size, f"Timestamp count {timestamp_count} doesn't match buffer size {final_size}"
        
        # Verify that the newest items were kept (higher indices have newer timestamps)
        with rss_processor._LOCATION_BATCH_LOCK:
            kept_indices = []
            for alert, tag, uuid in rss_processor._LOCATION_BATCH_BUFFER:
                alert_index = int(uuid.split('-')[-1])
                kept_indices.append(alert_index)
            
            print(f"Kept indices: {sorted(kept_indices)}")
            
            # Since we keep the newest items (highest timestamps), we should have indices 5-9
            for alert_index in kept_indices:
                assert alert_index >= 5, f"Older item {alert_index} was kept instead of newer items (5-9)"
        
        print("✓ Buffer size limit enforcement works correctly")
        
    finally:
        # Restore original buffer size
        rss_processor.MAX_BUFFER_SIZE = original_max_size
        # Clear test data
        with rss_processor._LOCATION_BATCH_LOCK:
            rss_processor._LOCATION_BATCH_BUFFER.clear()
            rss_processor._BUFFER_TIMESTAMPS.clear()

def test_age_based_cleanup():
    """Test that old items are removed from buffer"""
    print("Testing age-based buffer cleanup...")
    
    # Clear existing buffer
    with rss_processor._LOCATION_BATCH_LOCK:
        rss_processor._LOCATION_BATCH_BUFFER.clear()
        rss_processor._BUFFER_TIMESTAMPS.clear()
    
    # Set a short age limit for testing
    original_max_age = rss_processor.MAX_BUFFER_AGE_SECONDS
    rss_processor.MAX_BUFFER_AGE_SECONDS = 2  # 2 seconds
    
    try:
        current_time = time.time()
        
        # Add some old items
        for i in range(3):
            alert = {'uuid': f'old-uuid-{i}', 'title': f'Old Alert {i}'}
            uuid = alert['uuid']
            
            with rss_processor._LOCATION_BATCH_LOCK:
                rss_processor._LOCATION_BATCH_BUFFER.append((alert, 'old-tag', uuid))
                rss_processor._BUFFER_TIMESTAMPS[uuid] = current_time - 10  # 10 seconds ago (old)
        
        # Add some new items
        for i in range(3):
            alert = {'uuid': f'new-uuid-{i}', 'title': f'New Alert {i}'}
            uuid = alert['uuid']
            
            with rss_processor._LOCATION_BATCH_LOCK:
                rss_processor._LOCATION_BATCH_BUFFER.append((alert, 'new-tag', uuid))
                rss_processor._BUFFER_TIMESTAMPS[uuid] = current_time  # Current time (new)
        
        initial_size = len(rss_processor._LOCATION_BATCH_BUFFER)
        print(f"Added {initial_size} items (3 old, 3 new)")
        
        # Force cleanup by setting last cleanup time to old value
        rss_processor._LAST_CLEANUP_TIME = current_time - 1000
        
        # Trigger cleanup
        removed = rss_processor._cleanup_stale_buffer_items()
        print(f"Removed {removed} stale items")
        
        # Verify only new items remain
        with rss_processor._LOCATION_BATCH_LOCK:
            final_size = len(rss_processor._LOCATION_BATCH_BUFFER)
            remaining_uuids = [uuid for _, _, uuid in rss_processor._LOCATION_BATCH_BUFFER]
        
        print(f"Final buffer size: {final_size}")
        print(f"Remaining UUIDs: {remaining_uuids}")
        
        assert final_size == 3, f"Expected 3 items, got {final_size}"
        
        # Verify only new items remain
        for uuid in remaining_uuids:
            assert uuid.startswith('new-'), f"Old item {uuid} was not removed"
        
        print("✓ Age-based cleanup works correctly")
        
    finally:
        # Restore original age limit
        rss_processor.MAX_BUFFER_AGE_SECONDS = original_max_age
        # Clear test data
        with rss_processor._LOCATION_BATCH_LOCK:
            rss_processor._LOCATION_BATCH_BUFFER.clear()
            rss_processor._BUFFER_TIMESTAMPS.clear()

def test_retry_limit_handling():
    """Test that failed batches are eventually abandoned"""
    print("Testing retry limit handling...")
    
    # Clear existing retry counts
    rss_processor._BUFFER_RETRY_COUNT.clear()
    
    batch_id = "test-batch-123"
    
    # Test retry counting
    assert rss_processor._should_retry_batch(batch_id), "New batch should be retryable"
    
    # Simulate multiple failures
    for i in range(rss_processor.MAX_BATCH_RETRIES):
        rss_processor._increment_retry_count(batch_id)
        print(f"Failure {i+1}: retry count = {rss_processor._BUFFER_RETRY_COUNT[batch_id]}")
    
    # Should not retry after max attempts
    assert not rss_processor._should_retry_batch(batch_id), "Batch should not be retryable after max failures"
    
    # Test cleanup of failed batches
    failed_count = rss_processor._cleanup_failed_batches()
    print(f"Cleaned up {failed_count} failed batches")
    
    assert failed_count == 1, f"Expected 1 failed batch, got {failed_count}"
    assert batch_id not in rss_processor._BUFFER_RETRY_COUNT, "Failed batch should be removed from retry tracking"
    
    print("✓ Retry limit handling works correctly")

def test_stale_batch_marker_cleanup():
    """Test that stale _batch_queued markers are removed from alerts"""
    print("Testing stale batch marker cleanup...")
    
    current_time = time.time()
    
    # Create test alerts with different ages
    alerts = [
        # Old alert that should be cleaned
        {
            'uuid': 'old-alert',
            'title': 'Old Alert',
            'published': datetime.fromtimestamp(current_time - 10000, tz=timezone.utc),  # Very old
            'location_method': 'batch_pending',
            '_batch_queued': True
        },
        # Recent alert that should be kept
        {
            'uuid': 'new-alert',
            'title': 'New Alert',
            'published': datetime.fromtimestamp(current_time - 100, tz=timezone.utc),  # Recent
            'location_method': 'batch_pending',
            '_batch_queued': True
        },
        # Alert without batch marker
        {
            'uuid': 'normal-alert',
            'title': 'Normal Alert',
            'published': datetime.fromtimestamp(current_time - 10000, tz=timezone.utc),
            'location_method': 'keyword'
        }
    ]
    
    print(f"Created {len(alerts)} test alerts")
    
    # Run cleanup
    cleaned_count = rss_processor._clean_stale_batch_markers(alerts)
    print(f"Cleaned {cleaned_count} stale batch markers")
    
    # Verify results
    old_alert = alerts[0]
    new_alert = alerts[1]
    normal_alert = alerts[2]
    
    # Old alert should have batch marker removed and method changed
    assert '_batch_queued' not in old_alert, "Old alert should have _batch_queued removed"
    assert old_alert['location_method'] == 'fallback', f"Old alert method should be 'fallback', got '{old_alert['location_method']}'"
    assert old_alert['location_confidence'] == 'none', f"Old alert confidence should be 'none', got '{old_alert['location_confidence']}'"
    
    # New alert should keep batch marker
    assert new_alert.get('_batch_queued'), "New alert should keep _batch_queued"
    assert new_alert['location_method'] == 'batch_pending', "New alert should keep batch_pending method"
    
    # Normal alert should be unchanged
    assert normal_alert['location_method'] == 'keyword', "Normal alert should be unchanged"
    
    print("✓ Stale batch marker cleanup works correctly")

def test_buffer_health_metrics():
    """Test buffer health metrics collection"""
    print("Testing buffer health metrics...")
    
    # Clear existing data
    with rss_processor._LOCATION_BATCH_LOCK:
        rss_processor._LOCATION_BATCH_BUFFER.clear()
        rss_processor._BUFFER_TIMESTAMPS.clear()
    rss_processor._BUFFER_RETRY_COUNT.clear()
    
    current_time = time.time()
    
    # Add some test data
    for i in range(3):
        alert = {'uuid': f'metric-test-{i}', 'title': f'Test Alert {i}'}
        uuid = alert['uuid']
        
        with rss_processor._LOCATION_BATCH_LOCK:
            rss_processor._LOCATION_BATCH_BUFFER.append((alert, 'test-tag', uuid))
            rss_processor._BUFFER_TIMESTAMPS[uuid] = current_time - (i * 10)  # Different ages
    
    # Add some retry counts
    rss_processor._BUFFER_RETRY_COUNT['batch-1'] = 2
    rss_processor._BUFFER_RETRY_COUNT['batch-2'] = rss_processor.MAX_BATCH_RETRIES  # Failed batch
    
    # Get metrics
    metrics = rss_processor._get_buffer_health_metrics()
    
    print(f"Buffer health metrics: {metrics}")
    
    # Verify metrics
    assert metrics['buffer_size'] == 3, f"Expected buffer size 3, got {metrics['buffer_size']}"
    assert metrics['buffer_max_size'] == rss_processor.MAX_BUFFER_SIZE, "Max size should match constant"
    assert metrics['avg_item_age_seconds'] >= 0, "Average age should be non-negative"
    assert metrics['max_item_age_seconds'] >= metrics['avg_item_age_seconds'], "Max age should be >= average age"
    assert metrics['total_retry_attempts'] == 5, f"Expected 5 total retries, got {metrics['total_retry_attempts']}"  # 2 + 3
    assert metrics['permanently_failed_batches'] == 1, f"Expected 1 failed batch, got {metrics['permanently_failed_batches']}"
    assert 0 <= metrics['buffer_utilization_percent'] <= 100, "Utilization should be between 0-100%"
    
    print("✓ Buffer health metrics work correctly")
    
    # Cleanup
    with rss_processor._LOCATION_BATCH_LOCK:
        rss_processor._LOCATION_BATCH_BUFFER.clear()
        rss_processor._BUFFER_TIMESTAMPS.clear()
    rss_processor._BUFFER_RETRY_COUNT.clear()

def test_integration_scenario():
    """Test a realistic scenario with multiple failure modes"""
    print("Testing integration scenario with multiple failure modes...")
    
    # Clear all state
    with rss_processor._LOCATION_BATCH_LOCK:
        rss_processor._LOCATION_BATCH_BUFFER.clear()
        rss_processor._BUFFER_TIMESTAMPS.clear()
    rss_processor._BUFFER_RETRY_COUNT.clear()
    
    # Set aggressive limits for testing
    original_max_size = rss_processor.MAX_BUFFER_SIZE
    original_max_age = rss_processor.MAX_BUFFER_AGE_SECONDS
    original_max_retries = rss_processor.MAX_BATCH_RETRIES
    
    rss_processor.MAX_BUFFER_SIZE = 10
    rss_processor.MAX_BUFFER_AGE_SECONDS = 5  # 5 seconds
    rss_processor.MAX_BATCH_RETRIES = 2
    
    try:
        current_time = time.time()
        
        # Simulate adding many items over time
        print("Simulating buffer growth...")
        for i in range(20):  # More than buffer limit
            alert = {'uuid': f'integration-test-{i}', 'title': f'Test Alert {i}'}
            uuid = alert['uuid']
            
            # Some items are old, some are new
            item_age = 10 if i < 5 else 1  # First 5 are old
            
            with rss_processor._LOCATION_BATCH_LOCK:
                rss_processor._LOCATION_BATCH_BUFFER.append((alert, 'test-tag', uuid))
                rss_processor._BUFFER_TIMESTAMPS[uuid] = current_time - item_age
        
        print(f"Added 20 items, buffer size: {len(rss_processor._LOCATION_BATCH_BUFFER)}")
        
        # Simulate failed batch processing
        print("Simulating batch failures...")
        for attempt in range(5):
            batch_id = f"integration-batch-{attempt}"
            rss_processor._increment_retry_count(batch_id)
            rss_processor._increment_retry_count(batch_id)  # Two failures
            rss_processor._increment_retry_count(batch_id)  # Third failure - should exceed limit
        
        print(f"Created {len(rss_processor._BUFFER_RETRY_COUNT)} failed batches")
        
        # Force cleanup by resetting last cleanup time
        rss_processor._LAST_CLEANUP_TIME = 0
        
        # Run comprehensive cleanup
        print("Running comprehensive cleanup...")
        stale_removed = rss_processor._cleanup_stale_buffer_items()
        size_removed = rss_processor._enforce_buffer_size_limit()
        failed_cleaned = rss_processor._cleanup_failed_batches()
        
        print(f"Cleanup results: {stale_removed} stale, {size_removed} oversized, {failed_cleaned} failed batches")
        
        # Verify final state
        with rss_processor._LOCATION_BATCH_LOCK:
            final_buffer_size = len(rss_processor._LOCATION_BATCH_BUFFER)
            final_timestamp_count = len(rss_processor._BUFFER_TIMESTAMPS)
        
        final_retry_count = len(rss_processor._BUFFER_RETRY_COUNT)
        
        print(f"Final state: buffer={final_buffer_size}, timestamps={final_timestamp_count}, retries={final_retry_count}")
        
        # Assertions
        assert final_buffer_size <= rss_processor.MAX_BUFFER_SIZE, f"Buffer size {final_buffer_size} exceeds limit"
        assert final_timestamp_count == final_buffer_size, "Timestamp count should match buffer size"
        assert final_retry_count == 0, f"All failed batches should be cleaned up, got {final_retry_count}"
        
        # Verify only recent items remain
        with rss_processor._LOCATION_BATCH_LOCK:
            for alert, tag, uuid in rss_processor._LOCATION_BATCH_BUFFER:
                timestamp = rss_processor._BUFFER_TIMESTAMPS[uuid]
                age = current_time - timestamp
                assert age <= rss_processor.MAX_BUFFER_AGE_SECONDS, f"Item {uuid} is too old: {age}s"
        
        print("✓ Integration scenario passed all checks")
        
    finally:
        # Restore original limits
        rss_processor.MAX_BUFFER_SIZE = original_max_size
        rss_processor.MAX_BUFFER_AGE_SECONDS = original_max_age
        rss_processor.MAX_BATCH_RETRIES = original_max_retries
        
        # Clear test data
        with rss_processor._LOCATION_BATCH_LOCK:
            rss_processor._LOCATION_BATCH_BUFFER.clear()
            rss_processor._BUFFER_TIMESTAMPS.clear()
        rss_processor._BUFFER_RETRY_COUNT.clear()

def main():
    """Run all memory leak prevention tests"""
    print("🔬 Memory Leak Prevention Tests for Moonshot Location Batching")
    print("=" * 70)
    
    try:
        test_buffer_size_limit()
        print()
        test_age_based_cleanup()
        print()
        test_retry_limit_handling()
        print()
        test_stale_batch_marker_cleanup()
        print()
        test_buffer_health_metrics()
        print()
        test_integration_scenario()
        print()
        
        print("🎉 All memory leak prevention tests passed!")
        return True
        
    except AssertionError as e:
        print(f"❌ Test failed: {e}")
        return False
    except Exception as e:
        print(f"💥 Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
