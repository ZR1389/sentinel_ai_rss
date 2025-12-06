#!/usr/bin/env python3
"""
Test script to verify location_method fix
Checks if enhance_location_confidence() properly updates location_method
"""

import sys
sys.path.insert(0, '/home/zika/sentinel_ai_rss')

from services.threat_engine import enhance_location_confidence

def test_location_method_update():
    """Test that enhance_location_confidence updates location_method"""
    
    print("\n" + "=" * 80)
    print("TESTING: enhance_location_confidence() location_method update")
    print("=" * 80)
    
    # Test Case 1: Alert with city/country but unknown method
    test_cases = [
        {
            "name": "Indonesia flood (BBC) - unknown to legacy_precise",
            "input": {
                "title": "Death toll in Indonesia floods passes 500",
                "city": "Indonesia",
                "country": "Indonesia",
                "latitude": -2.5489,  # Simulated coordinates
                "longitude": 113.9213,
                "location_method": "unknown",
                "location_confidence": "medium"
            },
            "expected_method": "legacy_precise"
        },
        {
            "name": "US alert - none to legacy_precise",
            "input": {
                "title": "US Terror Alert",
                "city": "Washington DC",
                "country": "United States",
                "latitude": 38.9072,
                "longitude": -77.0369,
                "location_method": "none",
                "location_confidence": "low"
            },
            "expected_method": "legacy_precise"
        },
        {
            "name": "Lebanon alert - rejected to legacy_precise",
            "input": {
                "title": "Lebanon strikes",
                "city": "Beirut",
                "country": "Lebanon",
                "latitude": 33.3128,
                "longitude": 35.4783,
                "location_method": "rejected_validation",
                "location_confidence": "low"
            },
            "expected_method": "legacy_precise"
        },
        {
            "name": "Already TIER1 - feed_tag should stay",
            "input": {
                "title": "Some alert",
                "city": "New York",
                "country": "United States",
                "latitude": 40.7128,
                "longitude": -74.0060,
                "location_method": "feed_tag",
                "location_confidence": "high"
            },
            "expected_method": "feed_tag"  # Should NOT change
        },
        {
            "name": "Missing coordinates - auto-geocoded to legacy_precise",
            "input": {
                "title": "Location only",
                "city": "Paris",
                "country": "France",
                "location_method": "none",
                "location_confidence": "low"
            },
            "expected_method": "legacy_precise"  # Geocoding auto-fills coordinates
        }
    ]
    
    passed = 0
    failed = 0
    
    for test_case in test_cases:
        print(f"\n✓ Test: {test_case['name']}")
        print(f"  Input method: {test_case['input'].get('location_method')}")
        
        # Run the function
        result = enhance_location_confidence(test_case['input'].copy())
        actual_method = result.get('location_method')
        
        print(f"  Result method: {actual_method}")
        print(f"  Expected: {test_case['expected_method']}")
        
        if actual_method == test_case['expected_method']:
            print(f"  ✅ PASS")
            passed += 1
        else:
            print(f"  ❌ FAIL")
            failed += 1
    
    print("\n" + "=" * 80)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 80)
    
    return failed == 0

if __name__ == "__main__":
    try:
        success = test_location_method_update()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
