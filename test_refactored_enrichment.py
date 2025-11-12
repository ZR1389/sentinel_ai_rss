#!/usr/bin/env python3
"""
Test script for the refactored enrich_and_store_alerts function.
"""

import sys
import os
from datetime import datetime

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_refactored_enrich_and_store():
    """Test the refactored enrich_and_store_alerts function."""
    
    print("Testing refactored enrich_and_store_alerts()...")
    
    try:
        from threat_engine import enrich_and_store_alerts
        
        # Test with a small limit and no actual DB writes for safety
        start_time = datetime.now()
        
        # Test basic functionality
        result = enrich_and_store_alerts(
            region=None, 
            country="USA", 
            city=None, 
            category=None, 
            limit=5,  # Small limit for testing
            write_to_db=False  # Don't write to DB in test
        )
        
        duration = (datetime.now() - start_time).total_seconds()
        
        print(f"✅ Function completed successfully")
        print(f"  - Processing time: {duration:.2f} seconds")
        print(f"  - Result type: {type(result)}")
        print(f"  - Result count: {len(result) if isinstance(result, list) else 'N/A'}")
        
        if isinstance(result, list) and len(result) > 0:
            print(f"  - First result keys: {list(result[0].keys())[:10]}...")
            print(f"  - Sample alert title: {result[0].get('title', 'N/A')[:50]}...")
        
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Function test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_circuit_breaker():
    """Test the circuit breaker functionality."""
    
    print("\nTesting circuit breaker functionality...")
    
    try:
        from threat_engine import _check_circuit_breaker, _record_circuit_failure, _record_circuit_success
        
        # Test initial state
        assert _check_circuit_breaker() == True, "Circuit breaker should initially be CLOSED"
        print("✅ Initial state: CLOSED")
        
        # Test failure recording
        for i in range(5):  # Trigger failure threshold
            _record_circuit_failure()
        
        # Should now be OPEN
        assert _check_circuit_breaker() == False, "Circuit breaker should be OPEN after failures"
        print("✅ State after failures: OPEN")
        
        # Test success recovery
        _record_circuit_success()
        assert _check_circuit_breaker() == True, "Circuit breaker should reset to CLOSED on success"
        print("✅ State after success: CLOSED")
        
        return True
        
    except Exception as e:
        print(f"❌ Circuit breaker test failed: {e}")
        return False

def test_atomic_operations():
    """Test the atomic JSON operations."""
    
    print("\nTesting atomic JSON operations...")
    
    try:
        from threat_engine import _atomic_read_json, _atomic_write_json
        import tempfile
        
        # Create a temporary file for testing
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            test_file = f.name
        
        try:
            # Test data
            test_data = [
                {"uuid": "test-1", "title": "Test Alert 1"},
                {"uuid": "test-2", "title": "Test Alert 2"}
            ]
            
            # Test write
            write_success = _atomic_write_json(test_file, test_data)
            assert write_success == True, "Write should succeed"
            print("✅ Atomic write succeeded")
            
            # Test read
            read_data = _atomic_read_json(test_file)
            assert read_data == test_data, "Read data should match written data"
            print("✅ Atomic read succeeded")
            
            # Test read non-existent file
            non_existent_data = _atomic_read_json("non_existent_file.json")
            assert non_existent_data == [], "Non-existent file should return empty list"
            print("✅ Non-existent file handling works")
            
        finally:
            # Clean up
            if os.path.exists(test_file):
                os.unlink(test_file)
        
        return True
        
    except Exception as e:
        print(f"❌ Atomic operations test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Sentinel AI - Refactored Enrichment Function Test")
    print("="*60)
    
    # Setup basic environment
    os.environ["USE_MODULAR_ENRICHMENT"] = "true"
    
    # Run tests
    enrich_test_passed = test_refactored_enrich_and_store()
    circuit_test_passed = test_circuit_breaker()
    atomic_test_passed = test_atomic_operations()
    
    print("\n" + "="*60)
    print("TEST RESULTS:")
    print(f"  Refactored Enrichment: {'✅ PASS' if enrich_test_passed else '❌ FAIL'}")
    print(f"  Circuit Breaker: {'✅ PASS' if circuit_test_passed else '❌ FAIL'}")
    print(f"  Atomic Operations: {'✅ PASS' if atomic_test_passed else '❌ FAIL'}")
    
    if enrich_test_passed and circuit_test_passed and atomic_test_passed:
        print("\n🎉 All tests passed! The refactored enrichment function is ready.")
        sys.exit(0)
    else:
        print("\n💥 Some tests failed. Check the output above.")
        sys.exit(1)
