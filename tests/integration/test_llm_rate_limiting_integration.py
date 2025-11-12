#!/usr/bin/env python3
"""
Test suite for LLM Rate Limiting and Circuit Breaker Integration
Verifies that the system can handle high-volume requests (50k+/day) 
without hitting rate limits or causing cascading failures.
"""

import pytest
import asyncio
import time
import threading
from unittest.mock import Mock, patch
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_rate_limiter import (
    rate_limited, 
    get_all_rate_limit_stats, 
    get_all_circuit_breaker_stats,
    reset_circuit_breaker,
    openai_limiter, 
    xai_limiter, 
    deepseek_limiter, 
    moonshot_limiter,
    openai_circuit,
    xai_circuit,
    deepseek_circuit,
    moonshot_circuit
)

class TestLLMRateLimitingIntegration:
    """Test rate limiting integration across all LLM providers"""
    
    def setup_method(self):
        """Reset all limiters and circuit breakers before each test"""
        # Reset token buckets
        for limiter in [openai_limiter, xai_limiter, deepseek_limiter, moonshot_limiter]:
            limiter.tokens = limiter.capacity
            limiter.last_refill = time.time()
            limiter.metrics.clear()
        
        # Reset circuit breakers
        for service in ["openai", "xai", "deepseek", "moonshot"]:
            reset_circuit_breaker(service)
    
    def test_rate_limiting_under_load(self):
        """Test rate limiting behavior under high load (simulating 50k alerts/day)"""
        
        @rate_limited("xai")
        def mock_xai_call(timeout=10):
            return "success"
        
        # Configure low limit for testing
        xai_limiter.capacity = 10  # 10 tokens per minute
        xai_limiter.tokens = 10
        
        # Rapidly consume tokens
        start_time = time.time()
        success_count = 0
        timeout_count = 0
        
        for i in range(15):  # Try to make 15 calls (more than limit)
            try:
                result = mock_xai_call(timeout=1)  # Short timeout for test
                success_count += 1
            except TimeoutError:
                timeout_count += 1
        
        elapsed = time.time() - start_time
        
        # Should have consumed all tokens quickly and then started timing out
        assert success_count == 10, f"Expected 10 successful calls, got {success_count}"
        assert timeout_count == 5, f"Expected 5 timeouts, got {timeout_count}"
        
        # Get stats
        stats = get_all_rate_limit_stats()
        xai_stats = stats["xai"]
        
        assert xai_stats["requests_last_minute"] == 10
        assert xai_stats["tokens_consumed"] == 10
        assert xai_stats["remaining_tokens"] < 1
    
    def test_circuit_breaker_cascading_failure_prevention(self):
        """Test circuit breaker prevents cascading failures"""
        
        call_count = 0
        
        @rate_limited("openai") 
        def failing_openai_call(timeout=10):
            nonlocal call_count
            call_count += 1
            raise Exception("API Error")
        
        # Reset OpenAI circuit breaker
        openai_circuit.failure_count = 0
        openai_circuit.state = "closed"
        
        # Make calls until circuit opens
        exception_count = 0
        for i in range(10):
            try:
                failing_openai_call()
            except Exception as e:
                exception_count += 1
                if "Circuit breaker open" in str(e):
                    break
        
        # Circuit should be open now
        circuit_stats = get_all_circuit_breaker_stats()
        openai_cb_stats = circuit_stats["openai"]
        
        assert openai_cb_stats["state"] == "open"
        assert openai_cb_stats["failure_count"] >= 5  # Default failure threshold
        
        # Additional calls should fail immediately without hitting the API
        initial_call_count = call_count
        try:
            failing_openai_call()
        except Exception as e:
            assert "Circuit breaker open" in str(e)
        
        # Call count shouldn't increase (circuit breaker prevented the call)
        assert call_count == initial_call_count
    
    def test_multi_provider_load_balancing(self):
        """Test that different providers can handle load independently"""
        
        @rate_limited("deepseek")
        def deepseek_call(timeout=10):
            return "deepseek_success"
        
        @rate_limited("moonshot") 
        def moonshot_call(timeout=10):
            return "moonshot_success"
        
        # Set low limits for testing
        deepseek_limiter.capacity = 5
        deepseek_limiter.tokens = 5
        moonshot_limiter.capacity = 5 
        moonshot_limiter.tokens = 5
        
        deepseek_successes = 0
        moonshot_successes = 0
        
        # Make interleaved calls
        for i in range(10):
            try:
                if i % 2 == 0:
                    deepseek_call(timeout=1)
                    deepseek_successes += 1
                else:
                    moonshot_call(timeout=1)
                    moonshot_successes += 1
            except TimeoutError:
                pass  # Expected when rate limit exceeded
        
        # Both providers should have processed their quota
        assert deepseek_successes == 5
        assert moonshot_successes == 5
        
        # Check stats
        stats = get_all_rate_limit_stats()
        assert stats["deepseek"]["requests_last_minute"] == 5
        assert stats["moonshot"]["requests_last_minute"] == 5
    
    def test_concurrent_access_thread_safety(self):
        """Test thread safety under concurrent access"""
        
        @rate_limited("xai")
        def thread_safe_call(timeout=10):
            time.sleep(0.01)  # Simulate some work
            return "thread_success"
        
        # Configure for testing
        xai_limiter.capacity = 20
        xai_limiter.tokens = 20
        
        results = []
        errors = []
        
        def worker():
            for _ in range(5):
                try:
                    result = thread_safe_call(timeout=2)
                    results.append(result)
                except Exception as e:
                    errors.append(str(e))
        
        # Start multiple threads
        threads = []
        for _ in range(4):  # 4 threads * 5 calls = 20 calls (exactly the limit)
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # All calls should succeed (exactly at capacity)
        assert len(results) == 20
        assert len(errors) == 0
        
        # Stats should reflect 20 requests
        stats = get_all_rate_limit_stats()
        assert stats["xai"]["requests_last_minute"] == 20
    
    def test_production_rate_limits(self):
        """Test with production-like rate limits"""
        
        # Simulate production environment variables
        with patch.dict(os.environ, {
            "OPENAI_TPM_LIMIT": "3000",
            "XAI_TPM_LIMIT": "1500", 
            "DEEPSEEK_TPM_LIMIT": "5000",
            "MOONSHOT_TPM_LIMIT": "1000"
        }):
            # Import fresh limiters with new config
            from llm_rate_limiter import openai_limiter as prod_openai
            
            # Verify configuration
            assert prod_openai.capacity >= 3000  # Should use env var
            
            @rate_limited("openai")
            def production_call(timeout=10):
                return "prod_success"
            
            # Should be able to make many calls quickly
            success_count = 0
            for i in range(100):  # Well within limit
                try:
                    production_call(timeout=1)
                    success_count += 1
                except TimeoutError:
                    break
            
            # Should succeed with production limits
            assert success_count >= 50  # Should handle significant load
    
    def test_monitoring_endpoints(self):
        """Test monitoring and observability functions"""
        
        # Generate some activity
        @rate_limited("deepseek")
        def monitored_call(timeout=10):
            return "monitored"
        
        # Make some calls
        for i in range(3):
            try:
                monitored_call()
            except:
                pass
        
        # Test rate limit stats
        rate_stats = get_all_rate_limit_stats()
        assert "deepseek" in rate_stats
        assert "requests_last_minute" in rate_stats["deepseek"]
        assert "remaining_tokens" in rate_stats["deepseek"] 
        assert rate_stats["deepseek"]["requests_last_minute"] >= 3
        
        # Test circuit breaker stats
        circuit_stats = get_all_circuit_breaker_stats()
        assert "deepseek" in circuit_stats
        assert "state" in circuit_stats["deepseek"]
        assert circuit_stats["deepseek"]["state"] in ["closed", "open", "half_open"]
    
    def test_error_handling_robustness(self):
        """Test error handling and graceful degradation"""
        
        @rate_limited("moonshot")
        def unreliable_call(timeout=10):
            import random
            if random.random() < 0.7:  # 70% failure rate
                raise Exception("Simulated API failure")
            return "success"
        
        success_count = 0
        circuit_opened = False
        
        # Make calls until circuit opens
        for i in range(20):
            try:
                result = unreliable_call()
                success_count += 1
            except Exception as e:
                if "Circuit breaker open" in str(e):
                    circuit_opened = True
                    break
        
        # Circuit should eventually open due to failures
        circuit_stats = get_all_circuit_breaker_stats()
        moonshot_stats = circuit_stats["moonshot"]
        
        # Should have some failures recorded
        assert moonshot_stats["failure_count"] > 0
        
        # If enough failures occurred, circuit should be open
        if moonshot_stats["failure_count"] >= 5:
            assert moonshot_stats["state"] == "open"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
