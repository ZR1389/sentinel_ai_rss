#!/usr/bin/env python3
"""
Simple load test to validate that our timeout and performance optimizations 
handle concurrent requests properly without 504 Gateway Timeout errors.
"""

import asyncio
import aiohttp
import time
import json
from concurrent.futures import ThreadPoolExecutor

async def test_health_endpoint():
    """Test the health endpoint to ensure basic functionality"""
    async with aiohttp.ClientSession() as session:
        start_time = time.time()
        try:
            async with session.get('http://localhost:8080/healthz', timeout=10) as response:
                elapsed = time.time() - start_time
                if response.status == 200:
                    data = await response.json()
                    return True, elapsed, data.get('ok', False)
                else:
                    return False, elapsed, f"Status: {response.status}"
        except Exception as e:
            elapsed = time.time() - start_time
            return False, elapsed, str(e)

async def test_concurrent_health_requests(num_requests=10):
    """Test concurrent health requests to verify our optimizations handle load"""
    print(f"🔄 Testing {num_requests} concurrent health requests...")
    
    start_time = time.time()
    tasks = [test_health_endpoint() for _ in range(num_requests)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    total_time = time.time() - start_time
    
    successes = 0
    failures = 0
    total_response_time = 0
    
    for result in results:
        if isinstance(result, tuple):
            success, response_time, _ = result
            if success:
                successes += 1
                total_response_time += response_time
            else:
                failures += 1
        else:
            failures += 1
    
    avg_response_time = total_response_time / max(successes, 1)
    
    print(f"✅ {successes}/{num_requests} requests succeeded")
    print(f"❌ {failures} requests failed")
    print(f"⏱️  Average response time: {avg_response_time:.3f}s")
    print(f"🕒 Total test time: {total_time:.3f}s")
    
    return successes == num_requests and avg_response_time < 2.0

async def main():
    print("🚀 Starting Load Test for Sentinel AI Optimizations")
    print("=" * 50)
    
    # First, verify the application is running
    print("📋 Checking if application is running...")
    success, response_time, result = await test_health_endpoint()
    
    if not success:
        print(f"❌ Application not responding: {result}")
        print("Make sure the application is running on http://localhost:8080")
        return False
    
    print(f"✅ Application responding in {response_time:.3f}s")
    print(f"📊 Health status: {result}")
    
    # Test concurrent requests
    test_results = []
    
    # Test with increasing load
    for num_requests in [5, 10, 20]:
        print(f"\n📋 Load Test with {num_requests} concurrent requests")
        result = await test_concurrent_health_requests(num_requests)
        test_results.append(result)
        
        if not result:
            print(f"⚠️  Load test failed at {num_requests} concurrent requests")
            break
        else:
            print(f"✅ Load test passed with {num_requests} concurrent requests")
    
    print("\n" + "=" * 50)
    print("📊 LOAD TEST SUMMARY")
    print("=" * 50)
    
    if all(test_results):
        print("🎉 All load tests passed! Our optimizations are handling concurrent requests well.")
        print("✅ No 504 Gateway Timeout errors observed")
        print("✅ Application responds quickly under load")
        return True
    else:
        print("⚠️  Some load tests failed. May need further optimization.")
        return False

if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n⏹️  Load test interrupted by user")
        exit(1)
    except Exception as e:
        print(f"\n❌ Load test failed with error: {e}")
        exit(1)
