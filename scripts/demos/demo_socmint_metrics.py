#!/usr/bin/env python3
"""
SOCMINT Cache Metrics Demo
Demonstrates cache hit/miss tracking and performance logging
"""

from socmint_service import (
    SocmintService, 
    get_cache_metrics, 
    reset_cache_metrics,
    log_cache_performance_summary
)
from utils.ioc_extractor import extract_social_media_iocs, enrich_alert_with_socmint

def demo_cache_metrics():
    """Demo cache metrics functionality."""
    print("=" * 70)
    print("SOCMINT CACHE METRICS DEMO")
    print("=" * 70)
    
    # Reset to start fresh
    reset_cache_metrics()
    print("\n1. Starting with clean metrics:")
    print(get_cache_metrics())
    
    # Simulate cache lookups
    service = SocmintService()
    
    print("\n2. Simulating cache lookups...")
    print("   - Lookup 1: test_user (expect miss)")
    result1 = service.get_cached_socmint_data('instagram', 'test_user', ttl_minutes=120)
    print(f"     Result: {result1.get('success')}")
    
    print("   - Lookup 2: another_user (expect miss)")
    result2 = service.get_cached_socmint_data('instagram', 'another_user', ttl_minutes=120)
    print(f"     Result: {result2.get('success')}")
    
    print("\n3. Current metrics:")
    metrics = get_cache_metrics()
    for key, value in metrics.items():
        print(f"   {key}: {value}")
    
    print("\n4. Performance Summary:")
    log_cache_performance_summary()
    
    # Demo IOC extraction
    print("\n5. IOC Extraction Demo:")
    test_text = """
    Breaking: Threat actor @malware_king posts leak on instagram
    Related accounts: https://instagram.com/cyber_group
    Facebook page: https://www.facebook.com/ransomware.updates
    Contact via telegram: t.me/hackers_channel
    """
    iocs = extract_social_media_iocs(test_text)
    print(f"   Found {len(iocs)} IOCs:")
    for ioc in iocs:
        print(f"   - {ioc['platform']}: {ioc['value']}")
    
    print("\n6. Metrics endpoint example response:")
    print("   GET /api/socmint/metrics")
    print("   Response:", {
        "status": "success",
        "metrics": get_cache_metrics()
    })
    
    print("\n7. Available endpoints:")
    print("   GET  /api/socmint/instagram/<username>")
    print("   POST /api/socmint/facebook")
    print("   GET  /api/socmint/status/<platform>/<identifier>")
    print("   GET  /api/socmint/metrics")
    print("   POST /api/socmint/metrics/reset")
    
    print("\n" + "=" * 70)
    print("Demo complete! Check logs above for detailed tracking.")
    print("=" * 70)

if __name__ == '__main__':
    demo_cache_metrics()
