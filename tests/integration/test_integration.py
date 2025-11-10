#!/usr/bin/env python3
"""
Test script to verify metrics integration with RSS processor

This script tests the metrics system integration without running the full
RSS processing pipeline. It validates that metrics are being collected
and can be retrieved properly.
"""

import sys
import os
import time
from typing import Dict, Any

# Add current directory to path to import local modules
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))  # Go up two levels to project root

def test_metrics_integration():
    """Test that metrics integration is working properly"""
    print("🔍 Testing RSS Processor Metrics Integration...")
    
    try:
        # Test importing metrics module
        print("\n1. Testing metrics module import...")
        from metrics import RSSProcessorMetrics
        metrics = RSSProcessorMetrics()
        print("✅ Metrics module imported successfully")
        
        # Test basic metric operations
        print("\n2. Testing basic metric operations...")
        
        # Test timing metrics
        start_time = time.time()
        time.sleep(0.1)  # Simulate some work
        processing_time = time.time() - start_time
        
        metrics.record_feed_processing_time(processing_time)
        metrics.record_location_extraction_time(0.05, method="test")
        metrics.record_batch_processing_time(0.03, batch_size=5)
        metrics.record_database_operation_time(0.02, operation="test_insert")
        metrics.record_llm_api_call_time(0.8, provider="test", operation="test_call")
        
        print("✅ Timing metrics recorded successfully")
        
        # Test counter metrics
        metrics.increment_error_count("test_category", "test_error")
        metrics.increment_alert_count(10)
        metrics.set_batch_size(5)
        
        print("✅ Counter metrics recorded successfully")
        
        # Test metrics retrieval
        print("\n3. Testing metrics retrieval...")
        summary = metrics.get_metrics_summary()
        
        if isinstance(summary, dict):
            print("✅ Metrics summary retrieved successfully")
            print(f"   Summary keys: {list(summary.keys())}")
        else:
            print("❌ Metrics summary format unexpected")
            return False
            
    except ImportError as e:
        print(f"❌ Failed to import metrics module: {e}")
        print("   This is expected if metrics.py doesn't exist yet")
        return False
    except Exception as e:
        print(f"❌ Error testing metrics: {e}")
        return False
    
    return True

def test_circuit_breaker_integration():
    """Test that circuit breaker integration is working"""
    print("\n🔐 Testing Circuit Breaker Integration...")
    
    try:
        # Test importing circuit breaker
        print("\n1. Testing circuit breaker import...")
        from moonshot_circuit_breaker import (
            get_moonshot_circuit_breaker, 
            CircuitBreakerOpenError,
            protected_moonshot_call
        )
        print("✅ Circuit breaker module imported successfully")
        
        # Test getting circuit breaker instance
        print("\n2. Testing circuit breaker instance...")
        cb = get_moonshot_circuit_breaker()
        stats = cb.get_stats()
        
        print("✅ Circuit breaker instance created")
        print(f"   Initial state: {stats['state']}")
        print(f"   Total calls: {stats['total_calls']}")
        
        # Test successful call
        print("\n3. Testing successful protected call...")
        def dummy_success_function():
            return "success"
        
        result = protected_moonshot_call(dummy_success_function)
        if result == "success":
            print("✅ Protected call executed successfully")
        else:
            print("❌ Protected call returned unexpected result")
            return False
            
        # Test circuit breaker stats after success
        stats_after = cb.get_stats()
        if stats_after['total_calls'] > stats['total_calls']:
            print("✅ Circuit breaker stats updated correctly")
        else:
            print("❌ Circuit breaker stats not updated")
            return False
            
    except ImportError as e:
        print(f"❌ Failed to import circuit breaker: {e}")
        return False
    except Exception as e:
        print(f"❌ Error testing circuit breaker: {e}")
        return False
    
    return True

def test_config_integration():
    """Test that centralized config integration is working"""
    print("\n⚙️  Testing Configuration Integration...")
    
    try:
        # Test importing config
        print("\n1. Testing config import...")
        from config import RSSConfig
        config = RSSConfig()
        print("✅ Config module imported successfully")
        
        # Test key configuration values
        print("\n2. Testing configuration values...")
        
        key_configs = {
            'timeout_sec': config.timeout_sec,
            'max_concurrency': config.max_concurrency, 
            'batch_limit': config.batch_limit,
            'host_throttle_enabled': config.host_throttle_enabled,
            'location_batch_threshold': config.location_batch_threshold,
            'geocode_enabled': config.geocode_enabled,
        }
        
        print("✅ Configuration values accessible:")
        for key, value in key_configs.items():
            print(f"   {key}: {value}")
            
        # Verify config is frozen (immutable)
        try:
            config.timeout_sec = 999
            print("❌ Config is not frozen - values can be modified!")
            return False
        except:
            print("✅ Config is properly frozen (immutable)")
            
    except ImportError as e:
        print(f"❌ Failed to import config: {e}")
        return False
    except Exception as e:
        print(f"❌ Error testing config: {e}")
        return False
    
    return True

def test_rss_processor_imports():
    """Test that RSS processor can import with new integrations"""
    print("\n📡 Testing RSS Processor Import with New Integrations...")
    
    try:
        print("\n1. Testing RSS processor import...")
        # This will test if the modified rss_processor.py imports without errors
        import rss_processor
        print("✅ RSS processor imported successfully with new integrations")
        
        # Test if metrics are available in the module
        if hasattr(rss_processor, 'metrics'):
            print("✅ Metrics object available in RSS processor")
        else:
            print("❌ Metrics object not found in RSS processor")
            return False
            
        # Test if config is available
        if hasattr(rss_processor, 'config'):
            print("✅ Config object available in RSS processor")
        else:
            print("❌ Config object not found in RSS processor")
            return False
            
    except ImportError as e:
        print(f"❌ Failed to import RSS processor: {e}")
        print("   This may indicate import dependency issues")
        return False
    except Exception as e:
        print(f"❌ Error testing RSS processor: {e}")
        return False
    
    return True

def main():
    """Run all integration tests"""
    print("🧪 RSS Processor Integration Test Suite")
    print("=" * 50)
    
    tests = [
        ("Metrics Integration", test_metrics_integration),
        ("Circuit Breaker Integration", test_circuit_breaker_integration), 
        ("Configuration Integration", test_config_integration),
        ("RSS Processor Import", test_rss_processor_imports),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        try:
            if test_func():
                print(f"✅ {test_name}: PASSED")
                passed += 1
            else:
                print(f"❌ {test_name}: FAILED")
                failed += 1
        except Exception as e:
            print(f"❌ {test_name}: ERROR - {e}")
            failed += 1
    
    print(f"\n{'='*50}")
    print(f"🏁 Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All integration tests passed! The Phase 1 implementation is working correctly.")
        return True
    else:
        print("⚠️  Some integration tests failed. Check the output above for details.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
