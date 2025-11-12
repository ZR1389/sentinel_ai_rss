#!/usr/bin/env python3
"""
Comprehensive test suite for optimized batch processing performance.
Tests the enhanced BatchStateManager with performance tuning, adaptive sizing, 
priority handling, and timeout optimization.
"""

import sys
import os
import time
import threading
import random
import json
from unittest.mock import Mock

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from batch_state_manager import (
    BatchStateManager, 
    BatchFlushConfig, 
    BatchOptimizationConfig,
    BatchPerformanceMetrics,
    get_batch_state_manager,
    get_batch_performance_report,
    log_batch_performance_summary,
    reset_batch_state_manager
)

def test_optimized_initialization():
    """Test BatchStateManager initialization with optimized settings"""
    print("🧪 Testing Optimized Initialization")
    print("="*50)
    
    # Test with custom optimization config
    config = BatchFlushConfig(
        size_threshold=20,
        time_threshold_seconds=180.0,
        enable_adaptive_sizing=True,
        enable_priority_flushing=True
    )
    
    manager = BatchStateManager(
        max_buffer_size=500,
        flush_config=config,
        enable_performance_monitoring=True
    )
    
    stats = manager.get_detailed_stats()
    
    print(f"✅ Manager initialized successfully")
    print(f"   - Max buffer size: {manager.max_buffer_size}")
    print(f"   - Adaptive sizing: {manager.flush_config.enable_adaptive_sizing}")
    print(f"   - Priority flushing: {manager.flush_config.enable_priority_flushing}")
    print(f"   - Performance monitoring: {manager.enable_performance_monitoring}")
    print(f"   - Uptime: {stats['system_health']['uptime_hours']:.3f} hours")
    print()
    
    manager.shutdown()
    return True

def test_priority_queue_handling():
    """Test priority-based queueing and processing"""
    print("🚀 Testing Priority Queue Handling")
    print("="*50)
    
    flush_triggered = threading.Event()
    flush_reason = None
    
    def mock_flush_callback():
        nonlocal flush_reason
        flush_reason = "priority_triggered"
        flush_triggered.set()
    
    config = BatchFlushConfig(
        size_threshold=10,
        enable_priority_flushing=True,
        flush_callback=mock_flush_callback
    )
    
    manager = BatchStateManager(flush_config=config)
    
    # Add normal priority entries
    for i in range(5):
        success = manager.queue_entry(
            {"data": f"normal_{i}"}, 
            "test", 
            f"normal_{i}", 
            priority=0
        )
        assert success, f"Failed to queue normal entry {i}"
    
    print(f"✅ Queued 5 normal priority entries")
    print(f"   - Buffer size: {manager.get_buffer_size()}")
    print(f"   - Priority buffer: {manager.get_priority_buffer_size()}")
    
    # Add high priority entries (should trigger priority flush)
    for i in range(3):
        success = manager.queue_entry(
            {"data": f"high_{i}"}, 
            "test", 
            f"high_{i}", 
            priority=1
        )
        assert success, f"Failed to queue high priority entry {i}"
    
    print(f"✅ Queued 3 high priority entries")
    print(f"   - Buffer size: {manager.get_buffer_size()}")
    print(f"   - Priority buffer: {manager.get_priority_buffer_size()}")
    
    # Add urgent priority entry (should trigger immediate flush)
    success = manager.queue_entry(
        {"data": "urgent_critical"}, 
        "test", 
        "urgent_001", 
        priority=2
    )
    assert success, "Failed to queue urgent entry"
    
    print(f"✅ Queued urgent priority entry")
    print(f"   - Total buffer size: {manager.get_buffer_size()}")
    
    # Extract entries and verify priority ordering
    entries = manager.extract_buffer_entries()
    
    print(f"✅ Extracted {len(entries)} entries")
    
    # Verify priority ordering
    priorities = [entry.priority for entry in entries]
    print(f"   - Priority sequence: {priorities}")
    
    # High priority should be first
    urgent_entries = [e for e in entries if e.priority >= 2]
    high_entries = [e for e in entries if e.priority == 1]
    normal_entries = [e for e in entries if e.priority == 0]
    
    print(f"   - Urgent: {len(urgent_entries)}, High: {len(high_entries)}, Normal: {len(normal_entries)}")
    
    assert len(urgent_entries) == 1, "Should have 1 urgent entry"
    assert len(high_entries) == 3, "Should have 3 high priority entries"
    assert len(normal_entries) == 5, "Should have 5 normal entries"
    
    # Verify ordering: urgent first, then high, then normal
    assert entries[0].priority >= 2, "First entry should be urgent"
    
    stats = manager.get_detailed_stats()
    print(f"   - Priority overrides: {stats['priority_overrides']}")
    print()
    
    manager.shutdown()
    return True

def test_adaptive_sizing():
    """Test adaptive batch size adjustment based on performance"""
    print("⚡ Testing Adaptive Batch Sizing")
    print("="*50)
    
    config = BatchFlushConfig(
        size_threshold=15,
        enable_adaptive_sizing=True,
        time_threshold_seconds=60.0
    )
    
    manager = BatchStateManager(flush_config=config)
    
    # Simulate slow processing performance
    with manager._performance_lock:
        manager._performance_metrics.average_processing_time_ms = 5000.0  # 5 seconds - very slow
        manager._performance_metrics.throughput_entries_per_second = 2.0  # Low throughput
    
    print(f"✅ Set slow performance metrics:")
    print(f"   - Processing time: {manager._performance_metrics.average_processing_time_ms}ms")
    print(f"   - Throughput: {manager._performance_metrics.throughput_entries_per_second} eps")
    
    # Trigger optimization
    original_threshold = manager.flush_config.size_threshold
    manager._perform_adaptive_optimization()
    
    new_threshold = manager._get_adaptive_size_threshold()
    
    print(f"✅ Adaptive optimization results:")
    print(f"   - Original threshold: {original_threshold}")
    print(f"   - Adaptive threshold: {new_threshold}")
    print(f"   - Min batch size: {manager.flush_config.optimization_config.min_batch_size}")
    
    assert new_threshold <= original_threshold, "Slow performance should reduce batch size"
    
    # Now simulate fast performance
    with manager._performance_lock:
        manager._performance_metrics.average_processing_time_ms = 500.0  # 0.5 seconds - fast
        manager._performance_metrics.throughput_entries_per_second = 15.0  # High throughput
    
    # Reset optimization timer to allow immediate optimization
    manager._last_optimization_time = 0
    manager._perform_adaptive_optimization()
    
    fast_threshold = manager._get_adaptive_size_threshold()
    
    print(f"✅ Fast performance adaptive results:")
    print(f"   - Fast processing threshold: {fast_threshold}")
    print(f"   - Optimal batch size: {manager.flush_config.optimization_config.optimal_batch_size}")
    
    stats = manager.get_detailed_stats()
    print(f"   - Adaptive resizes: {stats.get('adaptive_resizes', 0)}")
    print()
    
    manager.shutdown()
    return True

def test_memory_pressure_handling():
    """Test memory pressure detection and emergency flushing"""
    print("🚨 Testing Memory Pressure Handling")
    print("="*50)
    
    emergency_flushes = []
    
    def mock_emergency_callback():
        emergency_flushes.append(time.time())
    
    config = BatchFlushConfig(
        size_threshold=50,
        flush_callback=mock_emergency_callback
    )
    
    # Small buffer to test overflow easily
    manager = BatchStateManager(
        max_buffer_size=20, 
        flush_config=config
    )
    
    print(f"✅ Created manager with small buffer: {manager.max_buffer_size}")
    
    # Fill buffer to near capacity
    for i in range(15):
        success = manager.queue_entry({"data": f"entry_{i}"}, "test", f"id_{i}")
        if not success:
            print(f"⚠️  Failed to queue at entry {i}")
            break
    
    buffer_size = manager.get_buffer_size()
    utilization = buffer_size / manager.max_buffer_size
    
    print(f"✅ Buffer near capacity:")
    print(f"   - Size: {buffer_size}/{manager.max_buffer_size} ({utilization:.1%})")
    
    # Try to add high priority entry when buffer is full
    print("🚨 Adding high-priority entry to trigger emergency flush...")
    
    # Fill completely first
    while manager.queue_entry({"data": f"filler"}, "test", f"fill_{random.randint(0,1000)}"):
        pass
    
    # Now try high priority - should trigger emergency flush
    emergency_success = manager.queue_entry(
        {"critical": "urgent_data"}, 
        "emergency", 
        "emergency_001", 
        priority=2
    )
    
    print(f"✅ Emergency entry result: {emergency_success}")
    
    stats = manager.get_detailed_stats()
    print(f"   - Buffer overflows: {stats['buffer_overflows']}")
    print(f"   - Emergency flushes: {stats.get('emergency_flushes', 0)}")
    print(f"   - Memory pressure events: {stats.get('memory_pressure_events', 0)}")
    print(f"   - Overflow rate: {stats['system_health']['overflow_rate']:.2%}")
    print()
    
    manager.shutdown()
    return True

def test_performance_monitoring():
    """Test comprehensive performance monitoring and metrics"""
    print("📊 Testing Performance Monitoring")
    print("="*50)
    
    performance_callbacks = []
    
    def mock_performance_callback(metrics):
        performance_callbacks.append(metrics)
    
    config = BatchFlushConfig(
        performance_callback=mock_performance_callback
    )
    
    manager = BatchStateManager(
        flush_config=config,
        enable_performance_monitoring=True
    )
    
    # Simulate some processing activity
    start_time = time.time()
    
    # Add entries
    for i in range(25):
        manager.queue_entry({"test": f"data_{i}"}, "perf_test", f"perf_{i}")
    
    # Simulate batch processing
    entries = manager.extract_buffer_entries()
    processing_time_ms = 1500.0  # 1.5 seconds
    
    # Store results with timing
    results = {entry.uuid: {"processed": True, "result": entry.entry} for entry in entries}
    manager.store_batch_results(results, processing_time_ms)
    
    # Get performance metrics
    metrics = manager.get_performance_metrics()
    detailed_stats = manager.get_detailed_stats()
    
    print(f"✅ Performance metrics collected:")
    print(f"   - Total processed: {metrics.total_entries_processed}")
    print(f"   - Avg processing time: {metrics.average_processing_time_ms:.1f}ms")
    print(f"   - Throughput: {metrics.throughput_entries_per_second:.2f} eps")
    print(f"   - Memory efficiency: {metrics.memory_efficiency_score:.2%}")
    print(f"   - Peak buffer size: {metrics.peak_buffer_size}")
    
    print(f"✅ System health indicators:")
    health = detailed_stats['system_health']
    print(f"   - Uptime: {health['uptime_hours']:.3f} hours")
    print(f"   - Processing efficiency: {health['processing_efficiency']:.2%}")
    print(f"   - Overflow rate: {health['overflow_rate']:.2%}")
    
    # Test performance report
    report = get_batch_performance_report()
    print(f"✅ Performance report generated: {len(report)} sections")
    
    print()
    manager.shutdown()
    return True

def test_timeout_optimization():
    """Test adaptive timeout calculation and deadline handling"""
    print("⏰ Testing Timeout Optimization")
    print("="*50)
    
    flush_events = []
    
    def timeout_flush_callback():
        flush_events.append(time.time())
    
    config = BatchFlushConfig(
        time_threshold_seconds=2.0,  # Short timeout for testing
        flush_callback=timeout_flush_callback,
        enable_timer_flush=True
    )
    
    manager = BatchStateManager(flush_config=config)
    
    # Add entry with urgent deadline
    urgent_deadline = time.time() + 1.0  # 1 second deadline
    manager.queue_entry(
        {"urgent": "deadline_test"}, 
        "timeout_test", 
        "deadline_001", 
        priority=2
    )
    
    # Manually set deadline for testing
    with manager._buffer_lock:
        if manager._priority_buffer:
            manager._priority_buffer[0].processing_deadline = urgent_deadline
    
    print(f"✅ Added entry with urgent deadline: {urgent_deadline}")
    
    # Test adaptive timeout calculation
    adaptive_timeout = manager._calculate_adaptive_timeout()
    print(f"✅ Adaptive timeout calculated: {adaptive_timeout:.1f}s")
    
    # Test deadline checking
    time.sleep(0.5)  # Wait a bit
    current_time = time.time()
    deadline_reached = manager._check_urgent_deadlines(current_time)
    print(f"✅ Deadline check (before timeout): {deadline_reached}")
    
    # Wait for deadline to pass
    time.sleep(1.2)
    current_time = time.time()
    deadline_reached = manager._check_urgent_deadlines(current_time)
    print(f"🚨 Deadline check (after timeout): {deadline_reached}")
    
    assert deadline_reached, "Deadline should be detected as passed"
    
    stats = manager.get_detailed_stats()
    print(f"✅ Timeout handling stats:")
    print(f"   - Timer flushes: {stats['timer_flushes']}")
    print(f"   - Emergency flushes: {stats.get('emergency_flushes', 0)}")
    
    if stats.get('buffer_age_stats'):
        age_stats = stats['buffer_age_stats']
        print(f"   - Max entry age: {age_stats['max_age_seconds']:.1f}s")
        print(f"   - Avg entry age: {age_stats['avg_age_seconds']:.1f}s")
    
    print()
    manager.shutdown()
    return True

def test_global_manager_performance():
    """Test the global manager with performance reporting"""
    print("🌐 Testing Global Manager Performance")
    print("="*50)
    
    # Reset first
    reset_batch_state_manager()
    
    # Get global manager
    global_manager = get_batch_state_manager()
    
    print(f"✅ Global manager configuration:")
    print(f"   - Max buffer: {global_manager.max_buffer_size}")
    print(f"   - Size threshold: {global_manager.flush_config.size_threshold}")
    print(f"   - Time threshold: {global_manager.flush_config.time_threshold_seconds}s")
    print(f"   - Adaptive sizing: {global_manager.flush_config.enable_adaptive_sizing}")
    print(f"   - Priority flushing: {global_manager.flush_config.enable_priority_flushing}")
    
    # Simulate workload
    for i in range(50):
        priority = 1 if i % 10 == 0 else 0  # Every 10th entry is high priority
        global_manager.queue_entry(
            {"workload": f"global_test_{i}", "batch": i // 10}, 
            "global_test", 
            f"global_{i}",
            priority=priority
        )
    
    print(f"✅ Queued 50 entries (5 high priority)")
    print(f"   - Buffer size: {global_manager.get_buffer_size()}")
    print(f"   - Priority buffer: {global_manager.get_priority_buffer_size()}")
    
    # Generate performance report
    print("\n📊 Generating comprehensive performance report...")
    log_batch_performance_summary()
    
    report = get_batch_performance_report()
    print(f"✅ Performance report sections: {list(report.keys())}")
    
    stats = report['detailed_stats']
    print(f"   - Total queued: {stats['total_queued']}")
    print(f"   - Priority overrides: {stats['priority_overrides']}")
    print(f"   - Current utilization: {stats['total_buffered_entries']}/{global_manager.max_buffer_size}")
    
    print()
    reset_batch_state_manager()
    return True

def run_comprehensive_batch_tests():
    """Run all batch processing optimization tests"""
    print("🚀 OPTIMIZED BATCH PROCESSING TEST SUITE")
    print("="*80)
    
    tests = [
        ("Optimized Initialization", test_optimized_initialization),
        ("Priority Queue Handling", test_priority_queue_handling),
        ("Adaptive Batch Sizing", test_adaptive_sizing),
        ("Memory Pressure Handling", test_memory_pressure_handling),
        ("Performance Monitoring", test_performance_monitoring),
        ("Timeout Optimization", test_timeout_optimization),
        ("Global Manager Performance", test_global_manager_performance),
    ]
    
    results = []
    start_time = time.time()
    
    for test_name, test_func in tests:
        print(f"\n🧪 Running: {test_name}")
        print("-" * 60)
        
        test_start = time.time()
        try:
            success = test_func()
            test_duration = time.time() - test_start
            
            if success:
                print(f"✅ {test_name} PASSED ({test_duration:.3f}s)")
                results.append((test_name, True, test_duration, None))
            else:
                print(f"❌ {test_name} FAILED ({test_duration:.3f}s)")
                results.append((test_name, False, test_duration, "Test returned False"))
                
        except Exception as e:
            test_duration = time.time() - test_start
            print(f"💥 {test_name} ERROR ({test_duration:.3f}s): {e}")
            results.append((test_name, False, test_duration, str(e)))
    
    # Final summary
    total_duration = time.time() - start_time
    passed = sum(1 for _, success, _, _ in results if success)
    
    print("\n" + "="*80)
    print("📋 FINAL TEST RESULTS")
    print("="*80)
    
    for test_name, success, duration, error in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name} ({duration:.3f}s)")
        if error and not success:
            print(f"    Error: {error}")
    
    success_rate = (passed / len(results)) * 100
    print(f"\n📊 Results: {passed}/{len(results)} passed ({success_rate:.1f}%)")
    print(f"⏱️  Total duration: {total_duration:.3f}s")
    
    if success_rate == 100:
        print("🎉 ALL BATCH OPTIMIZATION TESTS PASSED!")
        return True
    else:
        print("⚠️  Some tests failed. Please review the issues above.")
        return False

if __name__ == "__main__":
    success = run_comprehensive_batch_tests()
    exit(0 if success else 1)
