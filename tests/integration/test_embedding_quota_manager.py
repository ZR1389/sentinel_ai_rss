#!/usr/bin/env python3
"""
Test script for embedding quota manager in risk_shared.py.
Tests quota tracking, fallback mechanisms, and thread safety.
"""

import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import Mock

def test_quota_metrics():
    """Test QuotaMetrics dataclass functionality."""
    print("=" * 60)
    print("Testing QuotaMetrics dataclass")
    print("=" * 60)
    
    # Import from risk_shared
    sys.path.insert(0, '/Users/zikarakita/Documents/sentinel_ai_rss')
    
    try:
        from risk_shared import QuotaMetrics
        
        # Test default initialization
        metrics = QuotaMetrics()
        if metrics.daily_tokens == 0 and metrics.daily_requests == 0:
            print("✓ Default initialization works")
        else:
            print("✗ Default initialization failed")
            return False
            
        # Test field assignment
        metrics.daily_tokens = 100
        metrics.daily_requests = 5
        metrics.last_reset = datetime.utcnow()
        
        if metrics.daily_tokens == 100 and metrics.daily_requests == 5:
            print("✓ Field assignment works")
        else:
            print("✗ Field assignment failed")
            return False
            
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False

def test_embedding_manager_basic():
    """Test basic EmbeddingManager functionality."""
    print("\n" + "=" * 60)
    print("Testing EmbeddingManager basic functionality")
    print("=" * 60)
    
    try:
        from risk_shared import EmbeddingManager
        
        # Test initialization
        manager = EmbeddingManager()
        print("✓ EmbeddingManager initialized successfully")
        
        # Test fallback hash
        text = "This is a test sentence for embedding."
        fallback = manager._fallback_hash(text)
        
        if isinstance(fallback, list) and len(fallback) == 10:
            print("✓ Fallback hash generates correct dimensions")
        else:
            print(f"✗ Fallback hash incorrect: {len(fallback)} dimensions")
            return False
            
        # Test consistency
        fallback2 = manager._fallback_hash(text)
        if fallback == fallback2:
            print("✓ Fallback hash is deterministic")
        else:
            print("✗ Fallback hash is not consistent")
            return False
            
        # Test empty text handling
        empty_fallback = manager._fallback_hash("")
        if len(empty_fallback) == 10 and all(x == 0.0 for x in empty_fallback):
            print("✓ Empty text handled correctly")
        else:
            print("✗ Empty text not handled correctly")
            return False
            
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False

def test_quota_enforcement():
    """Test quota checking and enforcement."""
    print("\n" + "=" * 60)
    print("Testing quota enforcement")
    print("=" * 60)
    
    try:
        from risk_shared import EmbeddingManager
        
        # Create manager with low limits for testing
        manager = EmbeddingManager()
        manager.daily_limit = 100  # Very low limit
        manager.request_limit = 5  # Very low request limit
        
        # Test quota checking
        short_text = "Short"
        
        # Should pass initially
        if manager._check_quota(short_text):
            print("✓ Quota check passes initially")
        else:
            print("✗ Quota check failed initially")
            return False
            
        # Exhaust request quota
        for i in range(5):
            if not manager._check_quota(short_text):
                break
        else:
            # One more should fail
            if not manager._check_quota(short_text):
                print("✓ Request quota enforcement works")
            else:
                print("✗ Request quota not enforced")
                return False
        
        # Reset for token testing
        manager.quota.daily_requests = 0
        manager.quota.daily_tokens = 0
        
        # Test token quota with long text
        long_text = "This is a very long text that should consume many tokens. " * 50
        
        # Should eventually hit token limit
        quota_hit = False
        for i in range(20):
            if not manager._check_quota(long_text):
                quota_hit = True
                break
                
        if quota_hit:
            print("✓ Token quota enforcement works")
        else:
            print("✗ Token quota not enforced")
            return False
            
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False

def test_daily_reset():
    """Test daily quota reset functionality."""
    print("\n" + "=" * 60)
    print("Testing daily quota reset")
    print("=" * 60)
    
    try:
        from risk_shared import EmbeddingManager
        
        manager = EmbeddingManager()
        
        # Set some usage
        manager.quota.daily_tokens = 500
        manager.quota.daily_requests = 10
        manager.quota.last_reset = datetime.utcnow() - timedelta(days=2)  # 2 days ago
        
        # Check quota - should reset
        test_text = "Test reset functionality"
        manager._check_quota(test_text)
        
        # Verify reset occurred
        if manager.quota.daily_tokens < 500:  # Should be reset and then incremented
            print("✓ Daily quota reset works")
        else:
            print(f"✗ Daily quota not reset: {manager.quota.daily_tokens}")
            return False
            
        # Verify last_reset updated
        now = datetime.utcnow()
        if (now - manager.quota.last_reset).seconds < 60:  # Should be very recent
            print("✓ Last reset timestamp updated")
        else:
            print("✗ Last reset timestamp not updated")
            return False
            
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False

def test_thread_safety():
    """Test thread safety of quota management."""
    print("\n" + "=" * 60)
    print("Testing thread safety")
    print("=" * 60)
    
    try:
        from risk_shared import EmbeddingManager
        
        manager = EmbeddingManager()
        manager.daily_limit = 1000
        manager.request_limit = 100
        
        successful_checks = []
        failed_checks = []
        
        def worker(thread_id):
            """Worker function for concurrent quota checking."""
            for i in range(5):
                text = f"Thread {thread_id} iteration {i}"
                if manager._check_quota(text):
                    successful_checks.append((thread_id, i))
                else:
                    failed_checks.append((thread_id, i))
                time.sleep(0.001)  # Small delay
        
        # Run concurrent workers
        print("Starting concurrent quota check test with 10 threads...")
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker, i) for i in range(10)]
            for future in futures:
                future.result()
        
        total_attempts = len(successful_checks) + len(failed_checks)
        print(f"✓ Total attempts: {total_attempts}")
        print(f"✓ Successful: {len(successful_checks)}")
        print(f"✓ Failed (quota exceeded): {len(failed_checks)}")
        
        # Verify quota tracking is consistent
        status = manager.get_quota_status()
        expected_requests = len(successful_checks)
        if status["daily_requests"] == expected_requests:
            print("✓ Thread-safe quota tracking verified")
        else:
            print(f"✗ Quota tracking inconsistent: {status['daily_requests']} vs {expected_requests}")
            return False
            
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False

def test_embedding_integration():
    """Test full embedding integration with quota."""
    print("\n" + "=" * 60)
    print("Testing embedding integration")
    print("=" * 60)
    
    try:
        from risk_shared import get_embedding, embedding_manager
        
        # Test without client (should use fallback)
        text = "Test embedding integration"
        result = get_embedding(text, None)
        
        if isinstance(result, list) and len(result) == 10:
            print("✓ get_embedding works without client")
        else:
            print("✗ get_embedding failed without client")
            return False
            
        # Test with mock client
        mock_client = Mock()
        mock_response = Mock()
        mock_response.data = [Mock()]
        mock_response.data[0].embedding = [0.1, 0.2, 0.3, 0.4, 0.5]
        mock_client.embeddings.create.return_value = mock_response
        
        # Set high quota to ensure API call
        embedding_manager.daily_limit = 10000
        embedding_manager.request_limit = 1000
        embedding_manager.quota.daily_tokens = 0
        embedding_manager.quota.daily_requests = 0
        
        result = get_embedding(text, mock_client)
        
        if result == [0.1, 0.2, 0.3, 0.4, 0.5]:
            print("✓ get_embedding works with mock client")
        else:
            print(f"✗ get_embedding failed with mock client: {result}")
            return False
            
        # Test quota status
        status = embedding_manager.get_quota_status()
        if all(key in status for key in ["daily_tokens", "daily_requests", "tokens_remaining"]):
            print("✓ Quota status reporting works")
        else:
            print("✗ Quota status reporting failed")
            return False
            
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False

def test_environment_configuration():
    """Test environment variable configuration."""
    print("\n" + "=" * 60)
    print("Testing environment configuration")
    print("=" * 60)
    
    try:
        # Set environment variables
        os.environ["EMBEDDING_QUOTA_DAILY"] = "5000"
        os.environ["EMBEDDING_REQUESTS_DAILY"] = "1000"
        
        from risk_shared import EmbeddingManager
        
        manager = EmbeddingManager()
        
        if manager.daily_limit == 5000:
            print("✓ EMBEDDING_QUOTA_DAILY environment variable works")
        else:
            print(f"✗ Daily limit not set correctly: {manager.daily_limit}")
            return False
            
        if manager.request_limit == 1000:
            print("✓ EMBEDDING_REQUESTS_DAILY environment variable works")
        else:
            print(f"✗ Request limit not set correctly: {manager.request_limit}")
            return False
            
        # Clean up
        del os.environ["EMBEDDING_QUOTA_DAILY"]
        del os.environ["EMBEDDING_REQUESTS_DAILY"]
        
        return True
        
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False

def main():
    """Run all tests."""
    print("Testing risk_shared.py embedding quota manager")
    print("=" * 80)
    
    all_tests_passed = True
    
    tests = [
        test_quota_metrics,
        test_embedding_manager_basic,
        test_quota_enforcement,
        test_daily_reset,
        test_thread_safety,
        test_embedding_integration,
        test_environment_configuration,
    ]
    
    for test in tests:
        if not test():
            all_tests_passed = False
    
    print("\n" + "=" * 80)
    if all_tests_passed:
        print("🎉 All tests passed! Embedding quota manager is working correctly.")
        print("✓ Quota tracking prevents credit burning")
        print("✓ Daily limits enforced with automatic reset")
        print("✓ Thread-safe quota management")
        print("✓ Deterministic fallback when quota exceeded")
        print("✓ Environment variable configuration")
        print("✓ Integration with existing embedding workflow")
    else:
        print("❌ Some tests failed. Please review the implementation.")
    
    return 0 if all_tests_passed else 1

if __name__ == "__main__":
    sys.exit(main())
