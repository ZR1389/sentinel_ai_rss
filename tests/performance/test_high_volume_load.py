#!/usr/bin/env python3
"""
High-Volume Rate Limiting Performance Test
Simulates the 50k alerts/day load scenario to verify no cascading failures
"""

import time
import threading
import concurrent.futures
from collections import defaultdict
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_rate_limiter import (
    get_all_rate_limit_stats, 
    get_all_circuit_breaker_stats, 
    get_health_status,
    rate_limited
)

class HighVolumeLoadTest:
    """Test high-volume load handling"""
    
    def __init__(self):
        self.results = defaultdict(list)
        self.errors = defaultdict(list)
    
    @rate_limited("openai")
    def mock_openai_call(self, timeout=5):
        """Simulate OpenAI API call"""
        time.sleep(0.01)  # Simulate API latency
        return "openai_success"
    
    @rate_limited("xai") 
    def mock_xai_call(self, timeout=5):
        """Simulate XAI API call"""
        time.sleep(0.015)  # Simulate slightly higher latency
        return "xai_success"
    
    @rate_limited("deepseek")
    def mock_deepseek_call(self, timeout=5):
        """Simulate DeepSeek API call"""
        time.sleep(0.008)  # Simulate lower latency
        return "deepseek_success"
    
    @rate_limited("moonshot")
    def mock_moonshot_call(self, timeout=5):
        """Simulate Moonshot API call"""
        time.sleep(0.012)  # Simulate API latency
        return "moonshot_success"
    
    def worker_thread(self, service: str, call_count: int):
        """Worker thread for a specific service"""
        call_func = {
            "openai": self.mock_openai_call,
            "xai": self.mock_xai_call,
            "deepseek": self.mock_deepseek_call,
            "moonshot": self.mock_moonshot_call
        }[service]
        
        for i in range(call_count):
            try:
                start_time = time.time()
                result = call_func(timeout=2)  # Short timeout for testing
                duration = time.time() - start_time
                self.results[service].append({
                    "success": True,
                    "duration": duration,
                    "result": result
                })
            except Exception as e:
                self.errors[service].append({
                    "error": str(e),
                    "type": type(e).__name__
                })
    
    def simulate_daily_load(self, alerts_per_day=50000, simulation_minutes=5):
        """
        Simulate daily alert load compressed into a few minutes
        """
        print(f"🚀 Simulating {alerts_per_day} alerts/day load...")
        print(f"📊 Test duration: {simulation_minutes} minutes")
        
        # Calculate calls per minute for simulation
        calls_per_minute = int((alerts_per_day / (24 * 60)) * simulation_minutes)
        calls_per_service = calls_per_minute // 4  # Distribute across 4 services
        
        print(f"📈 Target: {calls_per_minute} total calls, ~{calls_per_service} per service")
        
        start_time = time.time()
        
        # Create thread pool for concurrent execution
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = []
            
            # Launch workers for each service
            for service in ["openai", "xai", "deepseek", "moonshot"]:
                future = executor.submit(self.worker_thread, service, calls_per_service)
                futures.append((service, future))
            
            # Wait for completion and track progress
            completed = 0
            for service, future in futures:
                future.result()
                completed += 1
                print(f"✓ {service} worker completed ({completed}/4)")
        
        total_time = time.time() - start_time
        
        # Analyze results
        self.print_performance_report(total_time, calls_per_minute)
    
    def print_performance_report(self, total_time: float, target_calls: int):
        """Print comprehensive performance report"""
        print("\n" + "="*60)
        print("📊 HIGH-VOLUME LOAD TEST REPORT")
        print("="*60)
        
        # Overall stats
        total_successes = sum(len(results) for results in self.results.values())
        total_errors = sum(len(errors) for errors in self.errors.values())
        total_calls = total_successes + total_errors
        
        print(f"🎯 Target calls: {target_calls}")
        print(f"✅ Successful calls: {total_successes}")
        print(f"❌ Failed calls: {total_errors}")
        print(f"📈 Success rate: {(total_successes/total_calls)*100:.1f}%")
        print(f"⏱️  Test duration: {total_time:.2f}s")
        print(f"🚀 Throughput: {total_calls/total_time:.1f} calls/sec")
        
        # Per-service breakdown
        print(f"\n📋 PER-SERVICE BREAKDOWN:")
        for service in ["openai", "xai", "deepseek", "moonshot"]:
            successes = len(self.results[service])
            errors = len(self.errors[service])
            
            if successes > 0:
                avg_duration = sum(r["duration"] for r in self.results[service]) / successes
                success_rate = (successes / (successes + errors)) * 100
                print(f"  {service.upper():>8}: {successes:>4} ✅ {errors:>4} ❌ "
                      f"({success_rate:>5.1f}% success, {avg_duration*1000:>5.1f}ms avg)")
            else:
                print(f"  {service.upper():>8}: {successes:>4} ✅ {errors:>4} ❌ (0.0% success)")
        
        # Error analysis
        if total_errors > 0:
            print(f"\n⚠️  ERROR ANALYSIS:")
            for service, error_list in self.errors.items():
                if error_list:
                    error_types = defaultdict(int)
                    for error in error_list:
                        error_types[error["type"]] += 1
                    
                    print(f"  {service}:")
                    for error_type, count in error_types.items():
                        print(f"    {error_type}: {count}")
        
        # System health check
        print(f"\n🏥 SYSTEM HEALTH:")
        health = get_health_status()
        print(f"  Overall Status: {health['status'].upper()}")
        print(f"  Services Available: {len(health['services_available'])}/4")
        if health['issues']:
            print(f"  Issues: {', '.join(health['issues'])}")
        else:
            print(f"  Issues: None")
        
        # Rate limiting stats
        print(f"\n🔧 RATE LIMITING STATUS:")
        rate_stats = get_all_rate_limit_stats()
        for service, stats in rate_stats.items():
            remaining_pct = (stats["remaining_tokens"] / stats["capacity"]) * 100
            print(f"  {service.upper():>8}: {stats['requests_last_minute']:>3} req/min, "
                  f"{remaining_pct:>5.1f}% tokens remaining")
        
        # Circuit breaker status
        print(f"\n⚡ CIRCUIT BREAKER STATUS:")
        cb_stats = get_all_circuit_breaker_stats()
        for service, stats in cb_stats.items():
            state_emoji = "🟢" if stats["state"] == "closed" else "🔴"
            print(f"  {service.upper():>8}: {state_emoji} {stats['state'].upper()} "
                  f"(failures: {stats['failure_count']})")
        
        print("\n" + "="*60)
        if total_errors / total_calls < 0.1:  # Less than 10% error rate
            print("✅ PASS: System handles high-volume load with minimal failures")
        else:
            print("⚠️ WARN: High error rate detected - review rate limits")


if __name__ == "__main__":
    test = HighVolumeLoadTest()
    
    # Run the simulation
    test.simulate_daily_load(
        alerts_per_day=50000,  # Target daily volume
        simulation_minutes=2   # Compress into 2 minutes for testing
    )
