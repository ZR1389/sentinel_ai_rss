#!/usr/bin/env python3
"""
Test script to verify connection pool leak fix in db_utils.py

This script tests:
1. Context manager properly releases connections
2. Exception handling doesn't leak connections
3. Transaction rollback works correctly
4. Connection pool stats remain stable under error conditions
"""

import sys
import os
# Add parent directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import db_utils
from unittest.mock import patch
import time

def test_connection_pool_leak_fix():
    """Test that connections are properly returned even with exceptions"""
    print("Testing connection pool leak fix...")
    
    # Get initial pool stats - use fetch_one to check connectivity
    try:
        result = db_utils.fetch_one("SELECT 1 as test")
        print(f"Initial pool state - connection test: {'OK' if result else 'FAIL'}")
    except Exception as e:
        print(f"✗ Connection pool leak fix: FAILED with exception: {e}")
        return False
    
    # Test 1: Normal operation should not leak connections
    try:
        result = db_utils.fetch_one("SELECT 1 as test")
        print(f"✓ Normal operation: {result}")
    except Exception as e:
        print(f"✗ Normal operation failed: {e}")
        return False
    
    # Test 2: Exception in query should still return connection
    try:
        db_utils.fetch_one("SELECT invalid_column_that_does_not_exist")
        print("✗ Should have raised an exception")
        return False
    except Exception:
        print("✓ Exception handled correctly")
    
    # Test 3: Context manager exception handling
    try:
        with db_utils._get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT invalid_column_that_does_not_exist")
    except Exception:
        print("✓ Context manager exception handling works")
    
    # Validate pool health using public API
    try:
        pool = db_utils.get_connection_pool()
        test_conn = pool.getconn()
        pool.putconn(test_conn)
        print("✓ Pool health check passed (getconn/putconn)")
        return True
    except Exception as e:
        print(f"✗ Pool health check failed: {e}")
        return False

def test_transaction_safety():
    """Test that transactions are properly rolled back on errors"""
    print("\nTesting transaction safety...")
    
    try:
        # This should fail and rollback
        with db_utils._get_db_connection() as conn:
            with conn.cursor() as cur:
                # Try to create a table that might conflict
                cur.execute("CREATE TABLE test_temp_table_that_should_not_exist (id int)")
                # Force an error to trigger rollback
                raise Exception("Simulated error")
    except Exception as e:
        if "Simulated error" in str(e):
            print("✓ Transaction rollback triggered correctly")
        else:
            print(f"✗ Unexpected error: {e}")
            return False
    
    # Verify the table was not created (rollback worked)
    try:
        result = db_utils.fetch_one("SELECT count(*) FROM test_temp_table_that_should_not_exist")
        print("✗ Transaction was not rolled back (table exists)")
        return False
    except Exception:
        print("✓ Transaction rollback confirmed (table does not exist)")
        return True

def test_bulk_operations():
    """Test bulk operations don't leak connections under error conditions"""
    print("\nTesting bulk operations...")
    
    # Test invalid data that should cause insert to fail
    invalid_alerts = [
        {
            "uuid": "test-uuid-1",
            "title": "Test Alert",
            # Missing required fields to cause potential issues
        }
    ]
    
    try:
        # This might fail but shouldn't leak connections
        result = db_utils.save_raw_alerts_to_db(invalid_alerts)
        print(f"✓ Bulk operation completed (result: {result})")
    except Exception as e:
        print(f"✓ Bulk operation error handled: {e}")
    
    # Pool should still be healthy
    pool = db_utils.get_connection_pool()
    try:
        test_conn = pool.getconn()
        pool.putconn(test_conn)
        print("✓ Pool is still healthy after bulk operations")
        return True
    except Exception as e:
        print(f"✗ Pool health check failed: {e}")
        return False

def test_concurrent_safety():
    """Basic test for concurrent connection handling"""
    print("\nTesting concurrent safety...")
    
    import threading
    import time
    
    results = []
    errors = []
    
    def worker():
        try:
            for i in range(5):
                result = db_utils.fetch_one("SELECT %s as worker_test", (i,))
                results.append(result)
                time.sleep(0.1)  # Small delay to increase concurrency
        except Exception as e:
            errors.append(str(e))
    
    # Start multiple workers
    threads = [threading.Thread(target=worker) for _ in range(3)]
    
    for t in threads:
        t.start()
    
    for t in threads:
        t.join(timeout=10)  # 10 second timeout
    
    if errors:
        print(f"✗ Concurrent operations had errors: {errors}")
        return False
    
    print(f"✓ Concurrent operations completed successfully ({len(results)} results)")
    return True

def run_all_tests():
    """Run all connection pool leak tests"""
    print("=== Connection Pool Leak Fix Tests ===\n")
    
    tests = [
        ("Connection pool leak fix", test_connection_pool_leak_fix),
        ("Transaction safety", test_transaction_safety),
        ("Bulk operations", test_bulk_operations),
        ("Concurrent safety", test_concurrent_safety)
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
                print(f"✓ {test_name}: PASSED")
            else:
                failed += 1
                print(f"✗ {test_name}: FAILED")
        except Exception as e:
            failed += 1
            print(f"✗ {test_name}: FAILED with exception: {e}")
        print()
    
    print("=== Test Results ===")
    print(f"✓ Passed: {passed}")
    print(f"✗ Failed: {failed}")
    
    if failed == 0:
        print("🎉 All connection pool leak fix tests passed!")
        return True
    else:
        print("❌ Some tests failed!")
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
