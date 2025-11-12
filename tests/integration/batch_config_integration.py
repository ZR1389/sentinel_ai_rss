#!/usr/bin/env python3
"""
Integration utility for optimized batch processing with centralized configuration.
This module provides factory functions to create BatchStateManager instances
using the centralized CONFIG object for consistent configuration management.
"""

import logging
from typing import Optional, Callable

try:
    from config import CONFIG
    from batch_state_manager import (
        BatchStateManager, 
        BatchFlushConfig, 
        BatchOptimizationConfig,
        log_batch_performance_summary
    )
except ImportError as e:
    logging.getLogger(__name__).error(f"Failed to import dependencies: {e}")
    raise

logger = logging.getLogger(__name__)

def create_optimized_batch_manager(
    flush_callback: Optional[Callable] = None,
    performance_callback: Optional[Callable] = None,
    custom_config: Optional[dict] = None
) -> BatchStateManager:
    """
    Create an optimized BatchStateManager using centralized configuration.
    
    Args:
        flush_callback: Callback function for batch flush events
        performance_callback: Callback function for performance monitoring
        custom_config: Optional dict to override specific config values
        
    Returns:
        Configured BatchStateManager instance
    """
    try:
        # Get batch config from centralized configuration
        batch_config = CONFIG.batch_processing
        
        # Apply any custom overrides
        if custom_config:
            config_dict = {
                'max_buffer_size': custom_config.get('max_buffer_size', batch_config.max_buffer_size),
                'max_buffer_age_seconds': custom_config.get('max_buffer_age_seconds', batch_config.max_buffer_age_seconds),
                'max_result_age_seconds': custom_config.get('max_result_age_seconds', batch_config.max_result_age_seconds),
                'size_threshold': custom_config.get('size_threshold', batch_config.size_threshold),
                'time_threshold_seconds': custom_config.get('time_threshold_seconds', batch_config.time_threshold_seconds),
                'enable_adaptive_sizing': custom_config.get('enable_adaptive_sizing', batch_config.enable_adaptive_sizing),
                'enable_priority_flushing': custom_config.get('enable_priority_flushing', batch_config.enable_priority_flushing),
                'enable_performance_monitoring': custom_config.get('enable_performance_monitoring', batch_config.enable_performance_monitoring)
            }
        else:
            config_dict = {
                'max_buffer_size': batch_config.max_buffer_size,
                'max_buffer_age_seconds': batch_config.max_buffer_age_seconds,
                'max_result_age_seconds': batch_config.max_result_age_seconds,
                'size_threshold': batch_config.size_threshold,
                'time_threshold_seconds': batch_config.time_threshold_seconds,
                'enable_adaptive_sizing': batch_config.enable_adaptive_sizing,
                'enable_priority_flushing': batch_config.enable_priority_flushing,
                'enable_performance_monitoring': batch_config.enable_performance_monitoring
            }
        
        # Create optimization config
        optimization_config = BatchOptimizationConfig(
            optimal_batch_size=batch_config.optimal_batch_size,
            max_batch_size=batch_config.max_batch_size,
            min_batch_size=batch_config.min_batch_size,
            fast_flush_timeout=batch_config.fast_flush_timeout_sec,
            standard_timeout=batch_config.time_threshold_seconds,
            emergency_timeout=batch_config.emergency_timeout_sec,
            enable_dynamic_sizing=batch_config.enable_adaptive_sizing,
            performance_target_ms=batch_config.performance_target_ms,
            throughput_target_eps=batch_config.throughput_target_eps,
            memory_pressure_threshold=batch_config.memory_pressure_threshold,
            aggressive_flush_threshold=batch_config.aggressive_flush_threshold
        )
        
        # Create flush config
        flush_config = BatchFlushConfig(
            size_threshold=config_dict['size_threshold'],
            time_threshold_seconds=config_dict['time_threshold_seconds'],
            enable_timer_flush=batch_config.enable_timer_flush,
            enable_priority_flushing=config_dict['enable_priority_flushing'],
            enable_adaptive_sizing=config_dict['enable_adaptive_sizing'],
            flush_callback=flush_callback,
            performance_callback=performance_callback
        )
        
        # Set optimization config
        flush_config.optimization_config = optimization_config
        
        # Create manager
        manager = BatchStateManager(
            max_buffer_size=config_dict['max_buffer_size'],
            max_buffer_age_seconds=config_dict['max_buffer_age_seconds'],
            max_result_age_seconds=config_dict['max_result_age_seconds'],
            flush_config=flush_config,
            enable_performance_monitoring=config_dict['enable_performance_monitoring']
        )
        
        logger.info(f"Created optimized BatchStateManager from centralized config: "
                   f"buffer={config_dict['max_buffer_size']}, "
                   f"threshold={config_dict['size_threshold']}, "
                   f"adaptive={config_dict['enable_adaptive_sizing']}, "
                   f"priority={config_dict['enable_priority_flushing']}")
        
        return manager
        
    except Exception as e:
        logger.error(f"Failed to create optimized batch manager: {e}")
        raise

def create_high_performance_batch_manager(
    flush_callback: Optional[Callable] = None,
    performance_callback: Optional[Callable] = None
) -> BatchStateManager:
    """
    Create a high-performance BatchStateManager optimized for heavy workloads.
    
    Uses aggressive settings for maximum throughput.
    """
    high_perf_overrides = {
        'size_threshold': 15,  # Smaller batches for faster processing
        'time_threshold_seconds': 120.0,  # 2 minutes max wait
        'enable_adaptive_sizing': True,
        'enable_priority_flushing': True,
        'enable_performance_monitoring': True
    }
    
    return create_optimized_batch_manager(
        flush_callback=flush_callback,
        performance_callback=performance_callback,
        custom_config=high_perf_overrides
    )

def create_memory_efficient_batch_manager(
    flush_callback: Optional[Callable] = None,
    performance_callback: Optional[Callable] = None
) -> BatchStateManager:
    """
    Create a memory-efficient BatchStateManager for resource-constrained environments.
    
    Uses conservative settings to minimize memory usage.
    """
    memory_efficient_overrides = {
        'max_buffer_size': 200,  # Smaller buffer
        'size_threshold': 10,  # Smaller batches
        'time_threshold_seconds': 180.0,  # 3 minutes
        'max_result_age_seconds': 3600,  # 1 hour result retention
        'enable_adaptive_sizing': True,
        'enable_priority_flushing': True,
        'enable_performance_monitoring': False  # Disable to save memory
    }
    
    return create_optimized_batch_manager(
        flush_callback=flush_callback,
        performance_callback=performance_callback,
        custom_config=memory_efficient_overrides
    )

def log_batch_configuration_summary():
    """Log a summary of the current batch processing configuration"""
    try:
        batch_config = CONFIG.batch_processing
        
        logger.info("="*60)
        logger.info("📦 BATCH PROCESSING CONFIGURATION SUMMARY")
        logger.info("="*60)
        logger.info(f"🔢 Buffer Management:")
        logger.info(f"   - Max Buffer Size: {batch_config.max_buffer_size:,}")
        logger.info(f"   - Max Buffer Age: {batch_config.max_buffer_age_seconds}s ({batch_config.max_buffer_age_seconds/60:.1f}min)")
        logger.info(f"   - Max Result Age: {batch_config.max_result_age_seconds}s ({batch_config.max_result_age_seconds/3600:.1f}h)")
        
        logger.info(f"⚡ Performance Optimization:")
        logger.info(f"   - Size Threshold: {batch_config.size_threshold}")
        logger.info(f"   - Time Threshold: {batch_config.time_threshold_seconds}s ({batch_config.time_threshold_seconds/60:.1f}min)")
        logger.info(f"   - Optimal Batch Size: {batch_config.optimal_batch_size}")
        logger.info(f"   - Batch Size Range: {batch_config.min_batch_size}-{batch_config.max_batch_size}")
        
        logger.info(f"🚀 Advanced Features:")
        logger.info(f"   - Adaptive Sizing: {'✅' if batch_config.enable_adaptive_sizing else '❌'}")
        logger.info(f"   - Priority Flushing: {'✅' if batch_config.enable_priority_flushing else '❌'}")
        logger.info(f"   - Performance Monitoring: {'✅' if batch_config.enable_performance_monitoring else '❌'}")
        logger.info(f"   - Timer Flush: {'✅' if batch_config.enable_timer_flush else '❌'}")
        
        logger.info(f"⏱️  Timeout Optimization:")
        logger.info(f"   - Fast Flush: {batch_config.fast_flush_timeout_sec}s")
        logger.info(f"   - Emergency: {batch_config.emergency_timeout_sec}s")
        
        logger.info(f"🎯 Performance Targets:")
        logger.info(f"   - Processing Target: {batch_config.performance_target_ms}ms")
        logger.info(f"   - Throughput Target: {batch_config.throughput_target_eps} entries/sec")
        
        logger.info(f"💾 Memory Management:")
        logger.info(f"   - Memory Pressure Threshold: {batch_config.memory_pressure_threshold:.1%}")
        logger.info(f"   - Aggressive Flush Threshold: {batch_config.aggressive_flush_threshold:.1%}")
        logger.info("="*60)
        
    except Exception as e:
        logger.error(f"Failed to log batch configuration summary: {e}")

def get_batch_config_dict() -> dict:
    """Get batch configuration as a dictionary for external integrations"""
    try:
        batch_config = CONFIG.batch_processing
        
        return {
            'buffer_management': {
                'max_buffer_size': batch_config.max_buffer_size,
                'max_buffer_age_seconds': batch_config.max_buffer_age_seconds,
                'max_result_age_seconds': batch_config.max_result_age_seconds
            },
            'flush_triggers': {
                'size_threshold': batch_config.size_threshold,
                'time_threshold_seconds': batch_config.time_threshold_seconds
            },
            'optimization': {
                'optimal_batch_size': batch_config.optimal_batch_size,
                'min_batch_size': batch_config.min_batch_size,
                'max_batch_size': batch_config.max_batch_size,
                'enable_adaptive_sizing': batch_config.enable_adaptive_sizing,
                'enable_priority_flushing': batch_config.enable_priority_flushing,
                'enable_performance_monitoring': batch_config.enable_performance_monitoring
            },
            'timeouts': {
                'fast_flush_timeout_sec': batch_config.fast_flush_timeout_sec,
                'emergency_timeout_sec': batch_config.emergency_timeout_sec
            },
            'performance_targets': {
                'performance_target_ms': batch_config.performance_target_ms,
                'throughput_target_eps': batch_config.throughput_target_eps
            },
            'memory_management': {
                'memory_pressure_threshold': batch_config.memory_pressure_threshold,
                'aggressive_flush_threshold': batch_config.aggressive_flush_threshold
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to get batch config dict: {e}")
        return {}

def validate_batch_environment() -> bool:
    """Validate that batch processing environment is properly configured"""
    try:
        # Test config loading
        batch_config = CONFIG.batch_processing
        
        # Test manager creation
        test_manager = create_optimized_batch_manager()
        
        # Test basic operations
        success = test_manager.queue_entry({"test": True}, "validation", "test_001")
        if not success:
            logger.error("Failed basic queue operation test")
            return False
        
        # Test extraction
        entries = test_manager.extract_buffer_entries()
        if len(entries) != 1:
            logger.error(f"Expected 1 entry, got {len(entries)}")
            return False
        
        # Cleanup
        test_manager.shutdown()
        
        logger.info("✅ Batch processing environment validation successful")
        return True
        
    except Exception as e:
        logger.error(f"❌ Batch processing environment validation failed: {e}")
        return False

if __name__ == "__main__":
    # Demo the configuration integration
    print("🚀 Batch Processing Configuration Integration Demo")
    print("="*60)
    
    # Log configuration
    log_batch_configuration_summary()
    
    # Validate environment
    if validate_batch_environment():
        print("✅ Batch processing environment is ready!")
    else:
        print("❌ Batch processing environment validation failed!")
        exit(1)
        
    # Create different manager types
    print("\n📦 Creating different manager configurations:")
    
    # Standard optimized manager
    standard_manager = create_optimized_batch_manager()
    print(f"   - Standard: buffer={standard_manager.max_buffer_size}, threshold={standard_manager.flush_config.size_threshold}")
    standard_manager.shutdown()
    
    # High performance manager
    hp_manager = create_high_performance_batch_manager()
    print(f"   - High Performance: buffer={hp_manager.max_buffer_size}, threshold={hp_manager.flush_config.size_threshold}")
    hp_manager.shutdown()
    
    # Memory efficient manager
    me_manager = create_memory_efficient_batch_manager()
    print(f"   - Memory Efficient: buffer={me_manager.max_buffer_size}, threshold={me_manager.flush_config.size_threshold}")
    me_manager.shutdown()
    
    print("\n🎉 Batch processing integration demo completed successfully!")
