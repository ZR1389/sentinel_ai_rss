#!/usr/bin/env python3
"""
Monitoring script for Sentinel AI chat performance.
Run this periodically to track the effectiveness of our optimizations.
"""

import asyncio
import aiohttp
import time
import json
import datetime
import statistics
from typing import List, Dict, Any

class PerformanceMonitor:
    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self.results: List[Dict[str, Any]] = []
    
    async def test_endpoint(self, session: aiohttp.ClientSession, endpoint: str, timeout: int = 10) -> Dict[str, Any]:
        """Test a single endpoint and return performance metrics"""
        start_time = time.time()
        url = f"{self.base_url}{endpoint}"
        
        try:
            async with session.get(url, timeout=timeout) as response:
                response_time = time.time() - start_time
                
                return {
                    "endpoint": endpoint,
                    "status_code": response.status,
                    "response_time": response_time,
                    "success": response.status == 200,
                    "error": None,
                    "timestamp": datetime.datetime.now().isoformat()
                }
        except Exception as e:
            response_time = time.time() - start_time
            return {
                "endpoint": endpoint,
                "status_code": None,
                "response_time": response_time,
                "success": False,
                "error": str(e),
                "timestamp": datetime.datetime.now().isoformat()
            }
    
    async def run_health_check(self) -> Dict[str, Any]:
        """Run a comprehensive health check"""
        print(f"🏥 Running health check at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        async with aiohttp.ClientSession() as session:
            # Test health endpoint
            health_result = await self.test_endpoint(session, "/healthz")
            
            # Test options endpoint (CORS preflight)
            options_result = await self.test_endpoint(session, "/_options")
            
            results = [health_result, options_result]
            
            # Calculate metrics
            successful = [r for r in results if r["success"]]
            failed = [r for r in results if not r["success"]]
            
            response_times = [r["response_time"] for r in successful]
            
            health_check = {
                "timestamp": datetime.datetime.now().isoformat(),
                "total_tests": len(results),
                "successful": len(successful),
                "failed": len(failed),
                "success_rate": len(successful) / len(results) * 100,
                "avg_response_time": statistics.mean(response_times) if response_times else 0,
                "max_response_time": max(response_times) if response_times else 0,
                "min_response_time": min(response_times) if response_times else 0,
                "results": results
            }
            
            return health_check
    
    async def run_load_test(self, concurrent_requests: int = 5, timeout: int = 30) -> Dict[str, Any]:
        """Run a load test with concurrent requests"""
        print(f"⚡ Running load test with {concurrent_requests} concurrent requests...")
        
        start_time = time.time()
        
        async with aiohttp.ClientSession() as session:
            # Create concurrent health check tasks
            tasks = [self.test_endpoint(session, "/healthz", timeout) for _ in range(concurrent_requests)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            total_time = time.time() - start_time
            
            # Process results
            valid_results = [r for r in results if isinstance(r, dict)]
            successful = [r for r in valid_results if r["success"]]
            failed = [r for r in valid_results if not r["success"]]
            
            response_times = [r["response_time"] for r in successful]
            
            load_test = {
                "timestamp": datetime.datetime.now().isoformat(),
                "concurrent_requests": concurrent_requests,
                "total_time": total_time,
                "total_tests": len(valid_results),
                "successful": len(successful),
                "failed": len(failed),
                "success_rate": len(successful) / len(valid_results) * 100 if valid_results else 0,
                "avg_response_time": statistics.mean(response_times) if response_times else 0,
                "max_response_time": max(response_times) if response_times else 0,
                "min_response_time": min(response_times) if response_times else 0,
                "requests_per_second": concurrent_requests / total_time if total_time > 0 else 0
            }
            
            return load_test
    
    def print_health_summary(self, health_check: Dict[str, Any]):
        """Print a formatted health check summary"""
        print("\n📊 HEALTH CHECK SUMMARY")
        print("=" * 40)
        print(f"✅ Success Rate: {health_check['success_rate']:.1f}%")
        print(f"⏱️  Average Response Time: {health_check['avg_response_time']*1000:.1f}ms")
        print(f"⚡ Max Response Time: {health_check['max_response_time']*1000:.1f}ms")
        print(f"🔄 Tests: {health_check['successful']}/{health_check['total_tests']} passed")
        
        if health_check['failed'] > 0:
            print(f"❌ Failed Tests: {health_check['failed']}")
            for result in health_check['results']:
                if not result['success']:
                    print(f"  - {result['endpoint']}: {result['error']}")
    
    def print_load_summary(self, load_test: Dict[str, Any]):
        """Print a formatted load test summary"""
        print("\n🚀 LOAD TEST SUMMARY")
        print("=" * 40)
        print(f"🔄 Concurrent Requests: {load_test['concurrent_requests']}")
        print(f"✅ Success Rate: {load_test['success_rate']:.1f}%")
        print(f"⏱️  Average Response Time: {load_test['avg_response_time']*1000:.1f}ms")
        print(f"📊 Requests/Second: {load_test['requests_per_second']:.1f}")
        print(f"🕒 Total Test Time: {load_test['total_time']:.3f}s")
        
        # Performance evaluation
        if load_test['success_rate'] == 100 and load_test['avg_response_time'] < 1.0:
            print("🎉 EXCELLENT: All requests succeeded with fast response times!")
        elif load_test['success_rate'] >= 95 and load_test['avg_response_time'] < 2.0:
            print("✅ GOOD: High success rate with acceptable response times")
        elif load_test['success_rate'] >= 90:
            print("⚠️  WARNING: Some requests failed or slow response times")
        else:
            print("❌ CRITICAL: High failure rate or very slow response times")
    
    def save_results(self, filename: str = None):
        """Save monitoring results to a file"""
        if not filename:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"monitoring_results_{timestamp}.json"
        
        with open(filename, 'w') as f:
            json.dump(self.results, f, indent=2)
        
        print(f"📄 Results saved to {filename}")

async def main():
    """Main monitoring function"""
    print("🚀 Sentinel AI Performance Monitoring")
    print("=" * 50)
    
    monitor = PerformanceMonitor()
    
    # Run health check
    health_check = await monitor.run_health_check()
    monitor.results.append({"type": "health_check", "data": health_check})
    monitor.print_health_summary(health_check)
    
    # Run load test if health check passes
    if health_check['success_rate'] > 0:
        for concurrent in [5, 10]:
            load_test = await monitor.run_load_test(concurrent)
            monitor.results.append({"type": "load_test", "data": load_test})
            monitor.print_load_summary(load_test)
            
            # Break if performance degrades
            if load_test['success_rate'] < 90:
                print(f"⚠️  Stopping load tests due to poor performance at {concurrent} concurrent requests")
                break
    else:
        print("❌ Skipping load tests due to health check failures")
    
    # Save results
    monitor.save_results()
    
    print("\n" + "=" * 50)
    print("✅ Monitoring complete!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️  Monitoring interrupted by user")
    except Exception as e:
        print(f"\n❌ Monitoring failed: {e}")
        exit(1)
