#!/usr/bin/env python3
"""
Enhanced LLM Rate Limiting & Circuit Breaker Monitoring Demo
===========================================================

This script demonstrates the comprehensive monitoring, retry mechanisms, and 
analytics capabilities of the enhanced LLM rate limiting system.

Features demonstrated:
1. Real-time monitoring of rate limiters and circuit breakers
2. Issue detection and analysis
3. Intelligent retry with exponential backoff
4. System health assessment
5. Performance reporting
6. Background monitoring
"""

import sys
import os
import time
import random
import json
from datetime import datetime

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from monitoring.llm_rate_limiter import (
    # Core monitoring functions
    get_comprehensive_rate_limiter_stats,
    get_comprehensive_circuit_breaker_stats,
    get_health_status,
    get_system_performance_report,
    analyze_frequent_issues,
    log_monitoring_summary,
    
    # Service status functions
    get_service_status,
    reset_circuit_breaker,
    
    # Core components
    TokenBucket,
    EnhancedCircuitBreaker,
    retry_with_backoff,
    classify_error_for_retry,
    calculate_backoff_delay,
    RetryErrorType,
    
    # Background monitoring
    start_monitoring_thread
)


def print_header(title):
    """Print a formatted header"""
    print(f"\n{'='*80}")
    print(f"🔍 {title}")
    print(f"{'='*80}")


def print_section(title):
    """Print a formatted section"""
    print(f"\n{'🔧 ' + title}")
    print(f"{'-'*60}")


def simulate_api_load():
    """Simulate API load to generate monitoring data"""
    print_section("Simulating API Load for Monitoring Demo")
    
    # Create test components
    test_bucket = TokenBucket(tokens_per_minute=300, name="demo_service")  # 5 tokens/second
    test_circuit = EnhancedCircuitBreaker(failure_threshold=3, recovery_timeout=5, name="demo_service")
    
    print("📊 Generating simulated API traffic...")
    
    # Simulate various scenarios
    scenarios = [
        ("✅ Successful requests", lambda: "success", 10),
        ("⚠️ Rate limiting scenario", lambda: test_bucket.consume(100) or Exception("Rate limited"), 3),
        ("❌ Service failures", lambda: Exception("Service temporarily unavailable"), 4),
        ("🔄 Intermittent failures", lambda: "success" if random.random() > 0.3 else Exception("Transient error"), 8)
    ]
    
    for scenario_name, scenario_func, count in scenarios:
        print(f"\n{scenario_name}:")
        for i in range(count):
            try:
                if callable(scenario_func):
                    result = scenario_func()
                    if isinstance(result, Exception):
                        raise result
                    elif hasattr(result, '__call__'):
                        test_circuit.call(result)
                    else:
                        test_circuit.call(lambda: result)
                print(f"   Request {i+1}: ✅")
            except Exception as e:
                try:
                    test_circuit.call(lambda: Exception(str(e)))
                except:
                    pass
                print(f"   Request {i+1}: ❌ {e}")
            
            # Small delay for realistic simulation
            time.sleep(0.01)
    
    print(f"\n📈 Generated test data for demonstration")
    return test_bucket, test_circuit


def demonstrate_error_classification():
    """Demonstrate intelligent error classification"""
    print_section("Error Classification for Retry Decision Making")
    
    test_errors = [
        ("Connection timeout", Exception("Connection timed out after 30s")),
        ("Rate limiting", Exception("Rate limit exceeded (429): Too many requests")),
        ("Network failure", Exception("Network unreachable: DNS resolution failed")),
        ("Server error", Exception("500 Internal Server Error: Service temporarily unavailable")),
        ("Authentication", Exception("401 Unauthorized: Invalid API key")),
        ("Bad request", Exception("400 Bad Request: Invalid parameter format")),
        ("Unknown error", Exception("Unexpected error occurred"))
    ]
    
    print("🏷️  Error Type Classification:")
    for error_name, error in test_errors:
        error_type = classify_error_for_retry(error)
        retryable = error_type in [
            RetryErrorType.TRANSIENT_NETWORK,
            RetryErrorType.TIMEOUT,
            RetryErrorType.SERVER_ERROR,
            RetryErrorType.RATE_LIMIT
        ]
        
        retry_status = "🔄 Retryable" if retryable else "🚫 Non-retryable"
        print(f"   {error_name:<20} → {error_type.value:<20} {retry_status}")


def demonstrate_backoff_strategy():
    """Demonstrate exponential backoff calculations"""
    print_section("Exponential Backoff Strategy")
    
    print("⏰ Backoff Delay Progression:")
    for attempt in range(6):
        delay_no_jitter = calculate_backoff_delay(attempt, base_delay=1.0, jitter=False)
        delay_with_jitter = calculate_backoff_delay(attempt, base_delay=1.0, jitter=True)
        
        print(f"   Attempt {attempt}: {delay_no_jitter:.1f}s (with jitter: {delay_with_jitter:.1f}s)")
    
    print("\n🎯 Backoff with Maximum Delay Capping:")
    for attempt in range(4):
        delay = calculate_backoff_delay(attempt, base_delay=2.0, max_delay=10.0, jitter=False)
        print(f"   Attempt {attempt}: {delay:.1f}s (max 10s)")


def demonstrate_retry_mechanism():
    """Demonstrate retry mechanism with various scenarios"""
    print_section("Intelligent Retry Mechanism")
    
    print("🔄 Testing Retry Scenarios:")
    
    # Scenario 1: Eventually successful
    def flaky_service_success():
        flaky_service_success.attempt_count += 1
        if flaky_service_success.attempt_count < 3:
            raise Exception("Temporary service failure")
        return f"Success after {flaky_service_success.attempt_count} attempts"
    flaky_service_success.attempt_count = 0
    
    try:
        start_time = time.time()
        result = retry_with_backoff(
            flaky_service_success,
            max_retries=3,
            base_delay=0.1,
            context="flaky_service"
        )
        duration = time.time() - start_time
        print(f"   ✅ Scenario 1: {result} (took {duration:.2f}s)")
    except Exception as e:
        print(f"   ❌ Scenario 1: {e}")
    
    # Scenario 2: Max retries exceeded
    def always_failing_service():
        raise Exception("Persistent service failure")
    
    try:
        start_time = time.time()
        result = retry_with_backoff(
            always_failing_service,
            max_retries=2,
            base_delay=0.1,
            context="persistent_failure"
        )
        print(f"   ✅ Scenario 2: {result}")
    except Exception as e:
        duration = time.time() - start_time
        print(f"   ❌ Scenario 2: Failed after retries ({duration:.2f}s)")
    
    # Scenario 3: Non-retryable error
    def auth_error_service():
        raise Exception("401 Unauthorized: Invalid credentials")
    
    try:
        start_time = time.time()
        result = retry_with_backoff(
            auth_error_service,
            max_retries=3,
            base_delay=0.1,
            context="auth_error"
        )
        print(f"   ✅ Scenario 3: {result}")
    except Exception as e:
        duration = time.time() - start_time
        print(f"   ⚠️  Scenario 3: Non-retryable error detected ({duration:.2f}s)")


def demonstrate_real_time_monitoring():
    """Demonstrate real-time monitoring capabilities"""
    print_section("Real-Time Monitoring & Analytics")
    
    print("📊 Current System Status:")
    
    # Overall health status
    health = get_health_status()
    health_emoji = {"healthy": "💚", "degraded": "🟡", "critical": "🔴"}.get(health["status"], "❓")
    print(f"   {health_emoji} Overall Health: {health['status'].upper()} (Score: {health['health_score']:.0f}%)")
    print(f"   🔧 Available Services: {len(health['services_available'])}/4")
    print(f"   ⚠️  Total Issues: {health['total_issues']}")
    
    # Service-specific status
    print(f"\n🤖 Individual Service Status:")
    for service in ["openai", "xai", "deepseek", "moonshot"]:
        status = get_service_status(service)
        if "error" not in status:
            health_status = status["health_summary"]["overall_health"]
            health_emoji = {"healthy": "💚", "degraded": "🟡", "critical": "🔴"}.get(health_status, "❓")
            available = "🟢" if status["is_available"] else "🔴"
            
            print(f"   {service.upper():<8} {available} {health_emoji} {health_status}")
        else:
            print(f"   {service.upper():<8} ❌ Error: {status['error']}")


def demonstrate_issue_analysis():
    """Demonstrate automated issue analysis"""
    print_section("Automated Issue Detection & Analysis")
    
    analysis = analyze_frequent_issues()
    
    print(f"🔍 Issue Analysis Results:")
    print(f"   📊 Issues Found: {analysis['issues_found']}")
    print(f"   🏥 Service Health: {analysis['summary']['healthy_services']}/4 healthy, "
          f"{analysis['summary']['degraded_services']} degraded, {analysis['summary']['critical_services']} critical")
    
    if analysis["issues"]:
        print(f"\n⚠️  Detected Issues:")
        for i, issue in enumerate(analysis["issues"][:5], 1):  # Show top 5
            severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(issue["severity"], "❓")
            print(f"   {i}. {severity_emoji} {issue['service']}: {issue['type']}")
            print(f"      💡 {issue['recommendation']}")
    else:
        print(f"   ✅ No significant issues detected")
    
    if analysis["recommendations"]:
        print(f"\n💡 General Recommendations:")
        for rec in analysis["recommendations"]:
            print(f"   - {rec}")


def demonstrate_performance_reporting():
    """Demonstrate comprehensive performance reporting"""
    print_section("System Performance Reporting")
    
    print("📈 Generating System Performance Report...")
    
    report = get_system_performance_report()
    
    if "error" in report:
        print(f"   ❌ Report generation failed: {report['error']}")
        return
    
    # Executive summary
    exec_summary = report["executive_summary"]
    print(f"\n📋 Executive Summary:")
    print(f"   🏥 Overall Health: {exec_summary['overall_health'].upper()}")
    print(f"   📊 Health Score: {exec_summary['health_score']:.0f}%")
    print(f"   🔧 Service Availability: {exec_summary['service_availability']}")
    print(f"   ✅ Success Rate: {exec_summary['overall_success_rate']}")
    print(f"   🔍 Issues Detected: {exec_summary['issues_detected']}")
    
    # Performance metrics
    perf_metrics = report["performance_metrics"]
    print(f"\n📊 Performance Metrics:")
    print(f"   📤 Total Requests: {perf_metrics['total_requests']:,}")
    print(f"   ✅ Successful: {perf_metrics['successful_requests']:,}")
    print(f"   ❌ Failed: {perf_metrics['failed_requests']:,}")
    print(f"   📈 Success Rate: {perf_metrics['success_rate']:.1%}")
    
    # Recommendations
    recommendations = report["recommendations"]
    if recommendations["immediate"]:
        print(f"\n🚨 Immediate Actions Needed:")
        for issue in recommendations["immediate"][:3]:
            print(f"   - {issue['service']}: {issue['details']}")
    
    if recommendations["optimization"]:
        print(f"\n⚡ Optimization Opportunities:")
        for issue in recommendations["optimization"][:3]:
            print(f"   - {issue['service']}: {issue['details']}")


def demonstrate_detailed_metrics():
    """Show detailed rate limiting and circuit breaker metrics"""
    print_section("Detailed Monitoring Metrics")
    
    # Rate limiter metrics
    rate_stats = get_comprehensive_rate_limiter_stats()
    print(f"📊 Rate Limiter Detailed Metrics:")
    
    for service in ["openai", "xai", "deepseek", "moonshot"]:
        if service in rate_stats:
            stats = rate_stats[service]
            print(f"\n   🤖 {service.upper()}:")
            print(f"      🪣 Capacity: {stats['capacity']:,} tokens/min")
            print(f"      ⚡ Current Utilization: {stats['utilization']:.1%}")
            print(f"      📈 Requests (last min): {stats['requests_last_minute']}")
            print(f"      ✅ Success Rate: {stats['success_rate']:.1%}")
            print(f"      🏥 Health: {stats['health_status']}")
            
            if stats.get('denied_requests', 0) > 0:
                print(f"      ⛔ Denied Requests: {stats['denied_requests']}")
    
    # Circuit breaker metrics
    circuit_stats = get_comprehensive_circuit_breaker_stats()
    print(f"\n⚡ Circuit Breaker Detailed Metrics:")
    
    for service in ["openai", "xai", "deepseek", "moonshot"]:
        if service in circuit_stats:
            stats = circuit_stats[service]
            print(f"\n   🤖 {service.upper()}:")
            print(f"      🔧 State: {stats['state'].upper()}")
            print(f"      📊 Total Requests: {stats['total_requests']:,}")
            print(f"      ❌ Failure Rate: {stats['failure_rate']:.1%}")
            print(f"      ⏱️  Avg Response: {stats['avg_response_time']:.2f}s")
            print(f"      🏥 Health: {stats['health_status']}")
            
            if stats['error_types']:
                top_error = max(stats['error_types'].items(), key=lambda x: x[1])
                print(f"      🚫 Top Error: {top_error[0]} ({top_error[1]}x)")


def demonstrate_background_monitoring():
    """Demonstrate background monitoring setup"""
    print_section("Background Monitoring Setup")
    
    print("🎯 Background monitoring capabilities:")
    print("   - Continuous health assessment")
    print("   - Automated issue detection")
    print("   - Performance trend analysis") 
    print("   - Real-time alerting")
    
    print(f"\n⏰ Background monitoring can be started with:")
    print(f"   ```python")
    print(f"   from llm_rate_limiter import start_monitoring_thread")
    print(f"   monitor = start_monitoring_thread(interval=300)  # 5 minutes")
    print(f"   ```")
    
    print(f"\n📝 Manual monitoring summary:")
    log_monitoring_summary()


def main():
    """Run the comprehensive LLM monitoring demonstration"""
    
    print_header("Enhanced LLM Rate Limiting & Circuit Breaker Monitoring Demo")
    print(f"🚀 Starting comprehensive monitoring demonstration at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # Generate some test data
        test_bucket, test_circuit = simulate_api_load()
        
        # Demonstrate core features
        demonstrate_error_classification()
        demonstrate_backoff_strategy()
        demonstrate_retry_mechanism()
        demonstrate_real_time_monitoring()
        demonstrate_issue_analysis()
        demonstrate_performance_reporting()
        demonstrate_detailed_metrics()
        demonstrate_background_monitoring()
        
        print_header("Demo Summary")
        print("✅ All monitoring and retry features demonstrated successfully!")
        print("\n📋 Key Capabilities Shown:")
        capabilities = [
            "🔍 Real-time system health monitoring",
            "🤖 Service-specific status tracking",
            "🔄 Intelligent retry with exponential backoff",
            "🏷️  Smart error classification",
            "📊 Comprehensive performance metrics",
            "⚠️  Automated issue detection and analysis",
            "📈 System performance reporting",
            "🎯 Background monitoring setup"
        ]
        
        for capability in capabilities:
            print(f"   {capability}")
        
        print(f"\n💡 Next Steps:")
        print(f"   1. Review the detailed metrics and recommendations")
        print(f"   2. Set up background monitoring for continuous assessment")
        print(f"   3. Configure alerting based on health scores and issue detection")
        print(f"   4. Tune retry policies based on your specific requirements")
        
        print(f"\n📚 For detailed documentation, see: ENHANCED_LLM_MONITORING.md")
        
    except Exception as e:
        print(f"❌ Demo failed with error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        print(f"\n🎬 Demo completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
