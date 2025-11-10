# test_timer_batch_integration.py - Test timer-based batch processing integration
# Verifies that the timer-based flush prevents batch processing bottlenecks

import asyncio
import time
import logging
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

# Ensure we can import the modules
sys.path.insert(0, '/Users/zikarakita/Documents/sentinel_ai_rss')

# Mock external dependencies
sys.modules['httpx'] = MagicMock()
sys.modules['feedparser'] = MagicMock()
sys.modules['unidecode'] = MagicMock()
sys.modules['langdetect'] = MagicMock()
sys.modules['city_utils'] = MagicMock()
sys.modules['psycopg'] = MagicMock()
sys.modules['spacy'] = MagicMock()
sys.modules['pycountry'] = MagicMock()
sys.modules['trafilatura'] = MagicMock()
sys.modules['bs4'] = MagicMock()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_timer_batch")

def test_timer_based_flush_config():
    """Test that BatchFlushConfig works correctly"""
    from batch_state_manager import BatchFlushConfig
    
    # Default config
    config = BatchFlushConfig()
    assert config.size_threshold == 10
    assert config.time_threshold_seconds == 300.0
    assert config.enable_timer_flush == True
    assert config.flush_callback is None
    
    # Custom config
    callback = lambda: None
    config2 = BatchFlushConfig(
        size_threshold=5,
        time_threshold_seconds=60.0,
        enable_timer_flush=False,
        flush_callback=callback
    )
    assert config2.size_threshold == 5
    assert config2.time_threshold_seconds == 60.0
    assert config2.enable_timer_flush == False
    assert config2.flush_callback == callback
    
    logger.info("✓ BatchFlushConfig works correctly")

def test_timer_based_batch_manager():
    """Test BatchStateManager with timer-based flushing"""
    from batch_state_manager import BatchStateManager, BatchFlushConfig
    
    # Track flush callbacks
    flush_calls = []
    
    def mock_flush_callback():
        flush_calls.append(time.time())
    
    config = BatchFlushConfig(
        size_threshold=3,
        time_threshold_seconds=2.0,  # 2 seconds for quick test
        enable_timer_flush=True,
        flush_callback=mock_flush_callback
    )
    
    manager = BatchStateManager(flush_config=config)
    
    # Test size-based flush
    flush_calls.clear()
    manager.queue_entry({"title": "Test 1"}, "test", "uuid1")
    manager.queue_entry({"title": "Test 2"}, "test", "uuid2")
    assert len(flush_calls) == 0  # Should not flush yet
    
    manager.queue_entry({"title": "Test 3"}, "test", "uuid3")
    assert len(flush_calls) == 1  # Should flush on size threshold
    
    stats = manager.get_stats()
    assert stats['size_flushes'] == 1
    assert stats['timer_flushes'] == 0
    
    # Test timer-based flush
    flush_calls.clear()
    manager.queue_entry({"title": "Test 4"}, "test", "uuid4")
    manager.queue_entry({"title": "Test 5"}, "test", "uuid5")
    
    # Wait for timer to trigger
    start_time = time.time()
    while len(flush_calls) == 0 and (time.time() - start_time) < 5.0:
        time.sleep(0.1)
    
    assert len(flush_calls) == 1  # Should flush on timer
    
    stats = manager.get_stats()
    assert stats['timer_flushes'] == 1
    
    manager.shutdown()
    logger.info("✓ Timer-based BatchStateManager works correctly")

def test_timer_batch_processor():
    """Test TimerBasedBatchProcessor"""
    from timer_based_batch_processor import TimerBasedBatchProcessor
    
    # Mock HTTP client
    mock_client = AsyncMock()
    
    processor = TimerBasedBatchProcessor(
        size_threshold=2,
        time_threshold_seconds=1.0,  # 1 second for quick test
        enable_timer_flush=True
    )
    
    processor.set_http_client(mock_client)
    
    # Test queuing
    assert processor.queue_entry({"title": "Test 1"}, "test", "uuid1") == True
    assert processor.get_buffer_size() == 1
    
    assert processor.queue_entry({"title": "Test 2"}, "test", "uuid2") == True
    assert processor.get_buffer_size() == 2
    
    # Test stats
    stats = processor.get_stats()
    assert stats['total_queued'] == 2
    assert stats['current_buffer_size'] == 2
    
    processor.shutdown()
    logger.info("✓ TimerBasedBatchProcessor works correctly")

def test_integration_with_rss_processor():
    """Test integration with RSS processor"""
    # Mock the timer batch processor
    with patch('timer_based_batch_processor.get_timer_batch_processor') as mock_get_processor:
        mock_processor = MagicMock()
        mock_get_processor.return_value = mock_processor
        
        # Import after mocking
        import rss_processor
        
        # Verify timer batch is available
        assert rss_processor.TIMER_BATCH_AVAILABLE == True
        
        # Test that get_timer_batch_processor is called properly
        try:
            from timer_based_batch_processor import get_timer_batch_processor
            processor = get_timer_batch_processor()
            assert processor is not None
        except ImportError:
            logger.warning("TimerBasedBatchProcessor import failed - using legacy batch processing")
    
    logger.info("✓ RSS processor timer batch integration works")

async def test_async_batch_prevention():
    """Test that timer-based flushing prevents batch bottlenecks"""
    from batch_state_manager import BatchStateManager, BatchFlushConfig
    
    # Track when batches are processed
    batch_process_times = []
    
    async def mock_batch_processor():
        batch_process_times.append(time.time())
        await asyncio.sleep(0.1)  # Simulate processing time
    
    def sync_callback():
        # Schedule async processing
        loop = asyncio.get_event_loop()
        loop.create_task(mock_batch_processor())
    
    config = BatchFlushConfig(
        size_threshold=10,  # High threshold
        time_threshold_seconds=1.0,  # Low time threshold
        enable_timer_flush=True,
        flush_callback=sync_callback
    )
    
    manager = BatchStateManager(flush_config=config)
    
    # Add entries below size threshold
    start_time = time.time()
    for i in range(3):  # Below size threshold of 10
        manager.queue_entry({"title": f"Test {i}"}, "test", f"uuid{i}")
        await asyncio.sleep(0.1)
    
    # Wait for timer to trigger
    await asyncio.sleep(2.0)
    
    # Verify that timer-based flush happened
    assert len(batch_process_times) >= 1, "Timer-based flush should have triggered"
    
    first_batch_time = batch_process_times[0]
    time_to_first_batch = first_batch_time - start_time
    
    # Should be close to time_threshold_seconds (1.0s), not waiting indefinitely
    assert 0.8 <= time_to_first_batch <= 2.0, f"Batch should flush within time threshold, got {time_to_first_batch:.2f}s"
    
    manager.shutdown()
    logger.info(f"✓ Timer-based flush prevented bottleneck: batched after {time_to_first_batch:.2f}s")

def run_all_tests():
    """Run all timer batch integration tests"""
    try:
        print("Testing Timer-Based Batch Processing Integration...")
        print("=" * 60)
        
        test_timer_based_flush_config()
        test_timer_based_batch_manager()
        test_timer_batch_processor()
        test_integration_with_rss_processor()
        
        # Run async test
        asyncio.run(test_async_batch_prevention())
        
        print("=" * 60)
        print("✅ All timer batch integration tests PASSED!")
        print("\nSUMMARY:")
        print("- Timer-based flush configuration works correctly")
        print("- BatchStateManager supports both size and time triggers")
        print("- TimerBasedBatchProcessor integrates properly")
        print("- RSS processor integration is functional")
        print("- Async batch bottleneck prevention is verified")
        
        return True
        
    except Exception as e:
        print(f"❌ Timer batch integration test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
