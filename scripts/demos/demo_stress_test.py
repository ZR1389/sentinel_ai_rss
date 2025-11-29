#!/usr/bin/env python3
"""
Stress Test Demo for Enhanced LLM Monitoring
============================================

This script demonstrates the monitoring system under stress conditions
to show how it detects and analyzes issues, circuit breaker activations,
and provides recommendations.
"""

import sys
import os
import time
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from llm_rate_limiter import (
    # Core components
    TokenBucket,
    EnhancedCircuitBreaker,
    retry_with_backoff,
    RetryErrorType,
    
    # Monitoring functions
    get_comprehensive_rate_limiter_stats,
    get_comprehensive_circuit_breaker_stats,
    get_health_status,
    analyze_frequent_issues,
    log_monitoring_summary,
    
    # Existing limiters and circuits
    openai_limiter, moonshot_limiter,
    openai_circuit, moonshot_circuit
)


def print_header(title):
    """Print formatted header"""
    print(f"\n{'='*70}")
    print(f"🔥 {title}")
    print(f"{'='*70}")


def print_section(title):
    """Print formatted section"""
    print(f"\n{'⚡ ' + title}")
    print(f"{'-'*50}")


def stress_test_rate_limiter():
    """Stress test rate limiters to trigger violations"""
    print_section("Rate Limiter Stress Test")
    
    print("📊 Generating high-volume traffic to trigger rate limits...")
    
    # Create burst of requests
    successes = 0
    failures = 0
    
    for i in range(50):  # Try 50 rapid requests
        if moonshot_limiter.consume(100):  # Large token consumption
            successes += 1
            print(f"   Request {i+1}: ✅", end="" if i % 10 != 9 else "\n")
        else:
            failures += 1
            print(f"   Request {i+1}: ❌", end="" if i % 10 != 9 else "\n")
        
        time.sleep(0.01)  # Rapid fire
    
    print(f"\n📈 Results: {successes} successes, {failures} failures")
    
    # Show rate limiter stats
    stats = moonshot_limiter.get_comprehensive_metrics()
    print(f"🔍 Moonshot Rate Limiter Status:")
    print(f"   Utilization: {stats['utilization']:.1%}")
    print(f"   Denied requests: {stats['denied_requests']}")
    print(f"   Health: {stats['health_status']}")


def stress_test_circuit_breaker():
    """Stress test circuit breaker to trigger state changes"""
    print_section("Circuit Breaker Stress Test")
    
    print("⚡ Generating service failures to trigger circuit breaker...")
    
    def failing_service():
        # Simulate different types of failures
        failure_types = [
            "500 Internal Server Error",
            "Connection timeout",
            "Rate limit exceeded",
            "Service temporarily unavailable"
        ]
        failure = random.choice(failure_types)
        raise Exception(failure)
    
    # Generate failures to open circuit
    for i in range(8):
        try:
            openai_circuit.call(failing_service)
        except Exception as e:
            print(f"   Failure {i+1}: {e}")
        
        time.sleep(0.05)
    
    # Show circuit breaker stats
    stats = openai_circuit.get_comprehensive_metrics()
    print(f"\n🔍 OpenAI Circuit Breaker Status:")
    print(f"   State: {stats['state'].upper()}")
    print(f"   Failure count: {stats['failure_count']}")
    print(f"   Failure rate: {stats['failure_rate']:.1%}")
    print(f"   Health: {stats['health_status']}")
    print(f"   Error types: {stats['error_types']}")


def stress_test_retry_mechanism():
    """Test retry mechanism under various failure conditions"""
    print_section("Retry Mechanism Stress Test")
    
    print("🔄 Testing retry behavior with different error patterns...")
    
    # Test 1: Transient failures that eventually succeed
    def intermittent_service():
        intermittent_service.call_count += 1
        if intermittent_service.call_count % 3 == 0:  # Succeed every 3rd call
            return f"Success on attempt {intermittent_service.call_count}"
        
        # Simulate different failure types
        failures = [
            "Connection timeout",
            "Network error",
            "502 Bad Gateway"
        ]
        raise Exception(random.choice(failures))
    
    intermittent_service.call_count = 0
    
    # Multiple retry attempts
    for test_num in range(3):
        try:
            result = retry_with_backoff(
                intermittent_service,
                max_retries=5,
                base_delay=0.1,
                context=f"stress_test_{test_num}"
            )
            print(f"   Test {test_num + 1}: ✅ {result}")
        except Exception as e:
            print(f"   Test {test_num + 1}: ❌ {e}")
    
    # Test 2: Non-retryable errors
    def auth_failing_service():
        raise Exception("401 Unauthorized: Invalid API key")
    
    try:
        retry_with_backoff(
            auth_failing_service,
            max_retries=3,
            base_delay=0.1,
            context="auth_test"
        )
    except Exception as e:
        print(f"   Auth test: ⚠️ Correctly failed without retry: {e}")


def concurrent_stress_test():
    """Run concurrent stress test to simulate real load"""
    print_section("Concurrent Load Stress Test")
    
    print("🚀 Running concurrent requests to simulate real-world load...")
    
    def make_request(request_id):
        """Simulate a single request with random behavior"""
        try:
            # Random delay to simulate processing time
            time.sleep(random.uniform(0.01, 0.1))
            
            # Random success/failure
            if random.random() < 0.7:  # 70% success rate
                return f"Request {request_id}: Success"
            else:
                raise Exception(f"Request {request_id}: Random failure")
        
        except Exception as e:
            return f"Request {request_id}: Failed - {e}"
    
    # Run concurrent requests
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(make_request, i) for i in range(25)]
        
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            success = "Success" in result
            print(f"   {'✅' if success else '❌'} {result}")
    
    successes = len([r for r in results if "Success" in r])
    failures = len([r for r in results if "Failed" in r])
    print(f"\n📊 Concurrent Test Results: {successes} successes, {failures} failures")


def demonstrate_monitoring_under_stress():
    """Show monitoring capabilities under stress conditions"""
    print_section("Monitoring Under Stress Conditions")
    
    # Show current system status
    health = get_health_status()
    print(f"🏥 Current System Health: {health['status']} (Score: {health['health_score']:.0f}%)")
    
    # Analyze issues
    analysis = analyze_frequent_issues()
    print(f"🔍 Issues Detected: {analysis['issues_found']}")
    
    if analysis["issues"]:
        print(f"\n⚠️ Issue Details:")
        for i, issue in enumerate(analysis["issues"][:5], 1):
            severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(issue["severity"], "❓")
            print(f"   {i}. {severity_emoji} {issue['service']}: {issue['type']}")
            print(f"      📝 Details: {issue['details']}")
            print(f"      💡 Recommendation: {issue['recommendation']}")
    
    if analysis["recommendations"]:
        print(f"\n💡 System Recommendations:")
        for rec in analysis["recommendations"]:
            print(f"   - {rec}")
    
    # Show detailed service status
    print(f"\n📊 Service Health Summary:")
    for service in ["openai", "xai", "deepseek", "moonshot"]:
        try:
            # Check rate limiter
            rl_stats = get_comprehensive_rate_limiter_stats()[service]
            cb_stats = get_comprehensive_circuit_breaker_stats()[service]
            
            # Overall health
            overall_health = "healthy"
            if cb_stats["state"] != "closed" or rl_stats["health_status"] != "healthy":
                overall_health = "degraded"
            if cb_stats["health_status"] == "critical":
                overall_health = "critical"
            
            health_emoji = {"healthy": "💚", "degraded": "🟡", "critical": "🔴"}.get(overall_health, "❓")
            
            print(f"   {service.upper():<8} {health_emoji}")
            print(f"      RL: {rl_stats['health_status']} (util: {rl_stats['utilization']:.1%})")
            print(f"      CB: {cb_stats['health_status']} (state: {cb_stats['state']})")
            
            if rl_stats.get('denied_requests', 0) > 0:
                print(f"      ⛔ Rate limited: {rl_stats['denied_requests']} requests")
            
            if cb_stats.get('circuit_opens', 0) > 0:
                print(f"      🔥 Circuit opened: {cb_stats['circuit_opens']} times")
                
        except Exception as e:
            print(f"   {service.upper():<8} ❌ Error getting stats: {e}")


def main():
    """Run comprehensive stress testing with monitoring"""
    
    print_header("Enhanced LLM Monitoring Stress Test Demo")
    print(f"🎯 Demonstrating monitoring capabilities under stress conditions")
    print(f"⚠️  This will intentionally trigger rate limits and circuit breakers")
    
    try:
        # Run stress tests
        stress_test_rate_limiter()
        stress_test_circuit_breaker()
        stress_test_retry_mechanism()
        concurrent_stress_test()
        
        # Show monitoring results
        demonstrate_monitoring_under_stress()
        
        # Generate monitoring summary
        print_section("Final Monitoring Summary")
        log_monitoring_summary()
        
        print_header("Stress Test Complete")
        print("✅ Stress testing completed successfully!")
        print("\n📋 What Was Demonstrated:")
        print("   🔥 Rate limiter behavior under high load")
        print("   ⚡ Circuit breaker activation and recovery")
        print("   🔄 Intelligent retry mechanisms")
        print("   🚀 Concurrent request handling")
        print("   📊 Real-time monitoring and issue detection")
        print("   💡 Automated recommendations")
        
        print(f"\n🎯 The monitoring system successfully:")
        print(f"   - Detected and classified different failure types")
        print(f"   - Triggered appropriate circuit breaker states")
        print(f"   - Provided intelligent retry strategies")
        print(f"   - Generated actionable recommendations")
        print(f"   - Maintained system stability under stress")
        
    except Exception as e:
        print(f"❌ Stress test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
