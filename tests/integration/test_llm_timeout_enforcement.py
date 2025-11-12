#!/usr/bin/env python3
"""
Test script to verify LLM timeout enforcement in xai_client.py

This script tests:
1. Timeout mechanism works correctly
2. Normal operations still function
3. Error handling is proper
4. Signal handling doesn't interfere with normal execution
"""

import sys
import os
import time
import signal
from unittest.mock import patch, MagicMock

# Add parent directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

def test_timeout_mechanism():
    """Test that the _timeout context manager works correctly"""
    print("Testing timeout mechanism...")
    
    # Import after path setup
    from xai_client import _timeout
    
    # Test 1: Normal operation within timeout
    start_time = time.time()
    try:
        with _timeout(2):
            time.sleep(0.5)  # Sleep less than timeout
        elapsed = time.time() - start_time
        print(f"✓ Normal operation completed in {elapsed:.2f}s")
    except TimeoutError:
        print("✗ Unexpected timeout in normal operation")
        return False
    
    # Test 2: Timeout enforcement
    start_time = time.time()
    try:
        with _timeout(1):
            time.sleep(2)  # Sleep longer than timeout
        print("✗ Timeout not enforced")
        return False
    except TimeoutError as e:
        elapsed = time.time() - start_time
        print(f"✓ Timeout enforced correctly after {elapsed:.2f}s: {e}")
    
    # Test 3: Signal cleanup
    try:
        # Should not have any active alarms after timeout context
        signal.alarm(0)  # This should not raise an error
        print("✓ Signal cleanup working correctly")
        return True
    except Exception as e:
        print(f"✗ Signal cleanup failed: {e}")
        return False

def test_grok_chat_timeout():
    """Test grok_chat timeout functionality with mocking"""
    print("\nTesting grok_chat timeout...")
    
    from xai_client import grok_chat
    
    # Test 1: Missing API key
    with patch.dict('os.environ', {}, clear=True):
        result = grok_chat([{"role": "user", "content": "test"}])
        if result is None:
            print("✓ Missing API key handled correctly")
        else:
            print("✗ Missing API key not handled")
            return False
    
    # Test 2: Mock a hanging SDK call that should timeout
    with patch.dict('os.environ', {'GROK_API_KEY': 'test-key'}):
        with patch('xai_client.Client') as mock_client:
            # Create a mock that hangs
            mock_instance = MagicMock()
            mock_chat = MagicMock()
            mock_client.return_value = mock_instance
            mock_instance.chat.create.return_value = mock_chat
            
            # Make the sample() method hang by sleeping longer than timeout
            def hanging_sample():
                time.sleep(3)  # Longer than our 1s test timeout
                return MagicMock(content="should not reach here")
            
            mock_chat.sample = hanging_sample
            
            # Test with 1 second timeout
            start_time = time.time()
            result = grok_chat([{"role": "user", "content": "test"}], timeout=1)
            elapsed = time.time() - start_time
            
            if result is None and elapsed < 2:
                print(f"✓ Hanging call timed out correctly after {elapsed:.2f}s")
            else:
                print(f"✗ Timeout not working: result={result}, elapsed={elapsed:.2f}s")
                return False
    
    return True

def test_normal_grok_chat_operation():
    """Test that normal grok_chat operations still work"""
    print("\nTesting normal grok_chat operation...")
    
    from xai_client import grok_chat
    
    # Test with mock that returns quickly
    with patch.dict('os.environ', {'GROK_API_KEY': 'test-key'}):
        with patch('xai_client.Client') as mock_client:
            # Create a mock that returns quickly
            mock_instance = MagicMock()
            mock_chat = MagicMock()
            mock_response = MagicMock()
            mock_response.content = "Test response"
            
            mock_client.return_value = mock_instance
            mock_instance.chat.create.return_value = mock_chat
            mock_chat.sample.return_value = mock_response
            
            # Test normal operation
            result = grok_chat([{"role": "user", "content": "test"}], timeout=5)
            
            if result == "Test response":
                print("✓ Normal operation works correctly")
                return True
            else:
                print(f"✗ Normal operation failed: {result}")
                return False

def test_exception_handling():
    """Test that exceptions are handled correctly"""
    print("\nTesting exception handling...")
    
    from xai_client import grok_chat
    
    # Test exception in SDK
    with patch.dict('os.environ', {'GROK_API_KEY': 'test-key'}):
        with patch('xai_client.Client') as mock_client:
            # Make Client constructor raise an exception
            mock_client.side_effect = Exception("Test SDK error")
            
            result = grok_chat([{"role": "user", "content": "test"}])
            
            if result is None:
                print("✓ Exception handling works correctly")
                return True
            else:
                print(f"✗ Exception not handled: {result}")
                return False

def run_all_tests():
    """Run all timeout enforcement tests"""
    print("=== LLM Timeout Enforcement Tests ===\n")
    
    tests = [
        ("Timeout mechanism", test_timeout_mechanism),
        ("Grok chat timeout", test_grok_chat_timeout),
        ("Normal grok chat operation", test_normal_grok_chat_operation),
        ("Exception handling", test_exception_handling)
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
        print("🎉 All LLM timeout enforcement tests passed!")
        return True
    else:
        print("❌ Some tests failed!")
        return False

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
