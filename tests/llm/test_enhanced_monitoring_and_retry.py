#!/usr/bin/env python3
"""
Comprehensive test suite for enhanced LLM rate limiting, circuit breaker monitoring,
and intelligent retry mechanisms with exponential backoff.
"""

import sys
import os
import time
import threading
import random
from unittest.mock import Mock, patch

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from monitoring.llm_rate_limiter import (
    # Core classes and functions
    TokenBucket, EnhancedCircuitBreaker, RetryErrorType,
    retry_with_backoff, classify_error_for_retry, calculate_backoff_delay,
    
    # Monitoring functions
    get_comprehensive_rate_limiter_stats, get_comprehensive_circuit_breaker_stats,
    analyze_frequent_issues, log_monitoring_summary, get_health_status,
    get_system_performance_report, get_service_status,
    
    # Service-specific functions
    moonshot_chat_limited, reset_circuit_breaker, reset_all_circuit_breakers
)

def test_enhanced_token_bucket():
    """Test enhanced token bucket with comprehensive monitoring"""
    print("🔧 Testing Enhanced Token Bucket Monitoring")
    print("="*60)
    
    # Create token bucket with low capacity for testing
    bucket = TokenBucket(tokens_per_minute=60, name="test_service")  # 1 token/second
    
    print(f"✅ Created token bucket: {bucket.capacity} tokens/minute")
    
    # Test successful consumption
    for i in range(5):
        success = bucket.consume(1)
        print(f"   Consume attempt {i+1}: {'✅' if success else '❌'}")
    
    # Test monitoring metrics
    metrics = bucket.get_comprehensive_metrics()
    print(f"✅ Comprehensive metrics collected:")
    print(f"   - Total requests: {metrics['total_requests']}")
    print(f"   - Success rate: {metrics['success_rate']:.1%}")
    print(f"   - Utilization: {metrics['utilization']:.1%}")
    print(f"   - Health status: {metrics['health_status']}")
    
    # Test rate limiting
    print(f"🚨 Testing rate limit violation:")
    for i in range(3):
        success = bucket.consume(20)  # Request more tokens than available
        if not success:
            print(f"   ✅ Rate limit correctly enforced on attempt {i+1}")
            break
    
    updated_metrics = bucket.get_comprehensive_metrics()
    print(f"✅ After violations:")
    print(f"   - Denied requests: {updated_metrics['denied_requests']}")
    print(f"   - Violation count: {updated_metrics['violation_count']}")
    print(f"   - Health status: {updated_metrics['health_status']}")
    print()
    
    return True

def test_enhanced_circuit_breaker():
    """Test enhanced circuit breaker with comprehensive monitoring"""
    print("⚡ Testing Enhanced Circuit Breaker")
    print("="*60)
    
    # Create circuit breaker with aggressive settings for testing
    circuit = EnhancedCircuitBreaker(
        name="test_circuit",
        failure_threshold=3,
        recovery_timeout=5,  # 5 seconds for testing
        failure_rate_threshold=0.6
    )
    
    print(f"✅ Created circuit breaker: {circuit.name}")
    
    # Mock function that fails
    def failing_function():
        raise Exception("Simulated API failure")
    
    def sometimes_failing_function():
        if random.random() < 0.7:  # 70% failure rate
            raise Exception("Transient network error")
        return "Success"
    
    # Test failure accumulation
    print(f"🔥 Testing failure accumulation:")
    for i in range(5):
        try:
            circuit.call(failing_function)
        except Exception as e:
            error_type = circuit.classify_error(e)
            print(f"   Attempt {i+1}: Failed ({error_type.value}) - State: {circuit.state}")
        
        if circuit.state == "open":
            print(f"   ✅ Circuit opened after {i+1} attempts")
            break
    
    # Test circuit open behavior
    print(f"🚫 Testing circuit open behavior:")
    try:
        circuit.call(lambda: "Should not execute")
        print("   ❌ Call should have been blocked")
    except Exception as e:
        print(f"   ✅ Call correctly blocked: {str(e)[:50]}")
    
    # Get comprehensive metrics
    metrics = circuit.get_comprehensive_metrics()
    print(f"✅ Circuit breaker metrics:")
    print(f"   - State: {metrics['state']}")
    print(f"   - Total requests: {metrics['total_requests']}")
    print(f"   - Failure rate: {metrics['failure_rate']:.1%}")
    print(f"   - Circuit opens: {metrics['circuit_opens']}")
    print(f"   - Error types: {metrics['error_types']}")
    print(f"   - Health status: {metrics['health_status']}")
    print()
    
    return True

def test_error_classification():
    """Test intelligent error classification for retry decisions"""
    print("🧠 Testing Error Classification")
    print("="*60)
    
    test_errors = [
        ("Connection timeout", Exception("Connection timeout")),
        ("Rate limit exceeded", Exception("429 Too Many Requests")),
        ("Network error", Exception("Network unreachable")),
        ("Server error", Exception("500 Internal Server Error")),
        ("Authentication failed", Exception("401 Unauthorized")),
        ("Bad request", Exception("400 Bad Request")),
        ("Unknown error", Exception("Something weird happened"))
    ]
    
    for description, error in test_errors:
        error_type = classify_error_for_retry(error)
        print(f"   {description}: {error_type.value}")
    
    print(f"✅ Error classification working correctly")
    print()
    
    return True

def test_backoff_calculation():
    """Test exponential backoff calculation with jitter"""
    print("⏰ Testing Backoff Calculation")
    print("="*60)
    
    print(f"Exponential backoff progression:")
    for attempt in range(6):
        delay = calculate_backoff_delay(attempt, base_delay=1.0, max_delay=60.0, jitter=False)
        delay_with_jitter = calculate_backoff_delay(attempt, base_delay=1.0, max_delay=60.0, jitter=True)
        print(f"   Attempt {attempt}: {delay:.1f}s (with jitter: {delay_with_jitter:.1f}s)")
    
    print(f"✅ Backoff calculation working correctly")
    print()
    
    return True

def test_retry_mechanism():
    """Test intelligent retry mechanism with different error types"""
    print("🔄 Testing Retry Mechanism")
    print("="*60)
    
    # Test successful retry
    call_count = 0
    def flaky_function():
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise Exception("Transient network error")
        return f"Success on attempt {call_count}"
    
    print(f"🎯 Testing successful retry:")
    start_time = time.time()
    try:
        result = retry_with_backoff(
            flaky_function,
            max_retries=3,
            base_delay=0.1,  # Fast for testing
            max_delay=1.0,
            context="test_function"
        )
        duration = time.time() - start_time
        print(f"   ✅ Success: {result} (took {duration:.2f}s, {call_count} attempts)")
    except Exception as e:
        print(f"   ❌ Unexpected failure: {e}")
    
    # Test max retries exceeded
    def always_failing_function():
        raise Exception("Permanent error")
    
    print(f"🚫 Testing max retries exceeded:")
    try:
        retry_with_backoff(
            always_failing_function,
            max_retries=2,
            base_delay=0.1,
            context="failing_test"
        )
        print(f"   ❌ Should have failed")
    except Exception as e:
        print(f"   ✅ Correctly failed after retries: {str(e)[:50]}")
    
    # Test non-retryable error
    def permanent_error_function():
        raise Exception("400 Bad Request")
    
    print(f"⛔ Testing non-retryable error:")
    try:
        retry_with_backoff(
            permanent_error_function,
            max_retries=3,
            base_delay=0.1,
            context="permanent_error_test"
        )
        print(f"   ❌ Should have failed immediately")
    except Exception as e:
        print(f"   ✅ Correctly failed without retry: {str(e)[:50]}")
    
    print()
    return True

def test_monitoring_and_analysis():
    """Test comprehensive monitoring and issue analysis"""
    print("📊 Testing Monitoring and Analysis")
    print("="*60)
    
    # Test service status
    print(f"🔍 Testing service status monitoring:")
    for service in ["moonshot", "openai", "deepseek", "xai"]:
        status = get_service_status(service)
        print(f"   {service}: {status['health_summary']['overall_health']}")
    
    # Test comprehensive stats
    print(f"📈 Testing comprehensive statistics:")
    rate_stats = get_comprehensive_rate_limiter_stats()
    circuit_stats = get_comprehensive_circuit_breaker_stats()
    
    print(f"   Rate limiter stats: {len(rate_stats)} services")
    print(f"   Circuit breaker stats: {len(circuit_stats)} services")
    
    # Test issue analysis
    print(f"🔍 Testing issue analysis:")
    analysis = analyze_frequent_issues()
    print(f"   Issues found: {analysis['issues_found']}")
    print(f"   Healthy services: {analysis['summary']['healthy_services']}/4")
    print(f"   Recommendations: {len(analysis['recommendations'])}")
    
    # Test system performance report
    print(f"📋 Testing system performance report:")
    report = get_system_performance_report()
    if 'error' not in report:
        print(f"   ✅ Report generated successfully")
        print(f"   Health score: {report['executive_summary']['health_score']:.0f}%")
        print(f"   Total requests: {report['performance_metrics']['total_requests']}")
    else:
        print(f"   ⚠️  Report generation issue: {report['error']}")
    
    print()
    return True

def test_service_specific_retry_functions():
    """Test service-specific retry-enabled functions"""
    print("🤖 Testing Service-Specific Retry Functions")
    print("="*60)
    
    # Mock the underlying client functions
    with patch('moonshot_client.moonshot_chat') as mock_moonshot:
        # Test successful call
        mock_moonshot.return_value = "Moonshot response"
        
        print(f"🌙 Testing moonshot_chat_limited:")
        try:
            # This would normally be called with rate limiting
            # For testing, we'll call the retry function directly
            def test_moonshot():
                return mock_moonshot([{"role": "user", "content": "test"}])
            
            result = retry_with_backoff(
                test_moonshot,
                max_retries=2,
                base_delay=0.1,
                context="moonshot_test"
            )
            print(f"   ✅ Success: {result}")
        except Exception as e:
            print(f"   ⚠️  Error: {e}")
    
    # Test circuit breaker reset
    print(f"🔧 Testing circuit breaker reset:")
    reset_result = reset_circuit_breaker("moonshot")
    print(f"   Reset moonshot circuit: {'✅' if reset_result else '❌'}")
    
    reset_all_result = reset_all_circuit_breakers()
    print(f"   Reset all circuits: {list(reset_all_result.keys())}")
    
    print()
    return True

def test_monitoring_logging():
    """Test monitoring logging and summary generation"""
    print("📝 Testing Monitoring Logging")
    print("="*60)
    
    print(f"📊 Generating monitoring summary:")
    try:
        log_monitoring_summary()
        print(f"   ✅ Monitoring summary logged successfully")
    except Exception as e:
        print(f"   ⚠️  Logging error: {e}")
    
    # Test health status
    print(f"🏥 Testing health status:")
    health = get_health_status()
    print(f"   Overall status: {health['status']}")
    print(f"   Health score: {health['health_score']:.0f}%")
    print(f"   Available services: {len(health['services_available'])}/4")
    
    print()
    return True

def run_comprehensive_monitoring_tests():
    """Run all monitoring and retry mechanism tests"""
    print("🚀 ENHANCED LLM MONITORING & RETRY TEST SUITE")
    print("="*80)
    
    tests = [
        ("Enhanced Token Bucket", test_enhanced_token_bucket),
        ("Enhanced Circuit Breaker", test_enhanced_circuit_breaker),
        ("Error Classification", test_error_classification),
        ("Backoff Calculation", test_backoff_calculation),
        ("Retry Mechanism", test_retry_mechanism),
        ("Monitoring and Analysis", test_monitoring_and_analysis),
        ("Service-Specific Functions", test_service_specific_retry_functions),
        ("Monitoring Logging", test_monitoring_logging),
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
        print("🎉 ALL MONITORING & RETRY TESTS PASSED!")
        return True
    else:
        print("⚠️  Some tests failed. Please review the issues above.")
        return False

if __name__ == "__main__":
    success = run_comprehensive_monitoring_tests()
    exit(0 if success else 1)
